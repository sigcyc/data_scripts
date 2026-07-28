"""Data-driven summaries for events that already happened.

Sources (all keyless): the BLS public API v1 for CPI/PPI/payrolls actuals, and
FRED's fredgraph CSV endpoint for the fed funds target range, jobless claims,
GDP and PCE. Values reflect the current data vintage (later revisions included),
which matches the released figures for recently run dates. Any failure degrades
to the event's descriptive fallback text — never an exception.
"""
from __future__ import annotations

import json
import sys
from datetime import date as Date, timedelta
from functools import lru_cache

import requests

from .base import Event, month_name, prev_month
from .http_cache import TIMEOUT, cached_text

BLS_SERIES = {
    "cpi_sa": "CUSR0000SA0",
    "cpi_nsa": "CUUR0000SA0",
    "cpi_core_sa": "CUSR0000SA0L1E",
    "ppi_sa": "WPSFD4",
    "ppi_nsa": "WPUFD4",
    "payrolls": "CES0000000001",
    "unemp": "LNS14000000",
}


@lru_cache(maxsize=None)
def _bls_data(start_year: int, end_year: int) -> dict[str, dict[tuple[int, int], float]] | None:
    """{series_key: {(year, month): value}} or None when the API is unreachable."""

    def fetch() -> str:
        r = requests.post(
            "https://api.bls.gov/publicAPI/v1/timeseries/data/",
            json={"seriesid": sorted(BLS_SERIES.values()),
                  "startyear": str(start_year), "endyear": str(end_year)},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        if json.loads(r.text).get("status") != "REQUEST_SUCCEEDED":  # don't cache rate-limit errors
            raise RuntimeError(json.loads(r.text).get("message"))
        return r.text

    text = cached_text(f"bls_{start_year}_{end_year}.json", fetch, ttl_hours=6)
    if text is None:
        return None
    by_id = {}
    for series in json.loads(text)["Results"]["series"]:
        vals = {}
        for p in series["data"]:
            period = p["period"]
            if not period.startswith("M") or period == "M13":
                continue
            try:
                vals[(int(p["year"]), int(period[1:]))] = float(p["value"])
            except ValueError:  # placeholder values like "-"
                continue
        by_id[series["seriesID"]] = vals
    return {key: by_id.get(sid, {}) for key, sid in BLS_SERIES.items()}


@lru_cache(maxsize=None)
def _fred_series(series_id: str, start: Date, end: Date) -> dict[Date, float] | None:
    """Keyless FRED series via the fredgraph CSV endpoint.

    Windows are kept narrow (per event) — fredgraph times out on long daily ranges.
    """

    def fetch() -> str:
        r = requests.get(
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}",
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        if not r.text.startswith("observation_date"):
            raise RuntimeError("unexpected fredgraph payload")
        return r.text

    text = cached_text(f"fredgraph_{series_id}_{start}_{end}.csv", fetch, ttl_hours=24)
    if text is None:
        return None
    out = {}
    for line in text.splitlines()[1:]:
        day, _, val = line.partition(",")
        if val not in ("", "."):
            out[Date.fromisoformat(day)] = float(val)
    return out


def _change(vals: dict[tuple[int, int], float], y: int, m: int, years_back: int = 0) -> float | None:
    cur = vals.get((y, m))
    py, pm = (y - years_back, m) if years_back else prev_month(y, m)
    prior = vals.get((py, pm))
    if cur is None or prior is None:
        return None
    return (cur / prior - 1) * 100


def _bls_for_event(ev: Event) -> dict[str, dict[tuple[int, int], float]] | None:
    ry = ev.ref["year"]
    return _bls_data(ry - 1, max(ry, ev.dt.year))


def _inflation_text(label: str, parts: list[tuple[str, float | None]]) -> str | None:
    avail = [f"{text} {val:+.1f}%" for text, val in parts if val is not None]
    return f"{label}: {', '.join(avail)} (BLS)." if avail else None


def _cpi(ev: Event) -> str | None:
    data = _bls_for_event(ev)
    if data is None:
        return None
    y, m = ev.ref["year"], ev.ref["month"]
    return _inflation_text(f"CPI {month_name(y, m)}", [
        ("m/m", _change(data["cpi_sa"], y, m)),
        ("y/y", _change(data["cpi_nsa"], y, m, years_back=1)),
        ("core m/m", _change(data["cpi_core_sa"], y, m)),
    ])


def _ppi(ev: Event) -> str | None:
    data = _bls_for_event(ev)
    if data is None:
        return None
    y, m = ev.ref["year"], ev.ref["month"]
    return _inflation_text(f"PPI final demand {month_name(y, m)}", [
        ("m/m", _change(data["ppi_sa"], y, m)),
        ("y/y", _change(data["ppi_nsa"], y, m, years_back=1)),
    ])


def _nfp(ev: Event) -> str | None:
    data = _bls_for_event(ev)
    if data is None:
        return None
    y, m = ev.ref["year"], ev.ref["month"]
    cur, (py, pm) = data["payrolls"].get((y, m)), prev_month(y, m)
    prior, unemp = data["payrolls"].get((py, pm)), data["unemp"].get((y, m))
    if cur is None or prior is None:
        return None
    return (f"Nonfarm payrolls {cur - prior:+,.0f}k in {month_name(y, m)}"
            + (f"; unemployment rate {unemp:.1f}%" if unemp is not None else "") + " (BLS).")


def _claims(ev: Event) -> str | None:
    week_ending = ev.ref["week_ending"]
    icsa = _fred_series("ICSA", week_ending - timedelta(days=14), week_ending + timedelta(days=7))
    val = (icsa or {}).get(week_ending)
    if val is None:
        return None
    return f"Initial jobless claims {val / 1000:,.0f}k, week ending {week_ending} (DOL via FRED)."


def _value_on_or_before(series: dict[Date, float], d: Date, max_back: int = 10) -> tuple[Date, float] | None:
    for back in range(max_back + 1):
        day = d - timedelta(days=back)
        if day in series:
            return day, series[day]
    return None


def _fomc(ev: Event) -> str | None:
    day2 = ev.ref["day2"]
    window = (day2 - timedelta(days=15), day2 + timedelta(days=10))
    upper, lower = _fred_series("DFEDTARU", *window), _fred_series("DFEDTARL", *window)
    if not upper or not lower:
        return None
    before = _value_on_or_before(upper, day2)  # target change is effective the next day
    after = _value_on_or_before(upper, day2 + timedelta(days=3))
    if before is None or after is None or after[0] <= day2:
        return None  # new range not yet published
    (_, bu), (after_day, au) = before, after
    al = lower.get(after_day)
    rng = f"{al:.2f}–{au:.2f}%" if al is not None else f"upper bound {au:.2f}%"
    if au == bu:
        return f"FOMC held the target range at {rng}."
    verb, bp = ("cut" if au < bu else "raised"), abs(au - bu) * 100
    return f"FOMC {verb} rates {bp:.0f}bp to {rng} (upper bound was {bu:.2f}%)."


def _gdp(ev: Event) -> str | None:
    q, qy = ev.ref["q"], ev.ref["qy"]
    qstart = Date(qy, 3 * (q - 1) + 1, 1)
    # real GDP, % change q/q SAAR
    series = _fred_series("A191RL1Q225SBEA", qstart - timedelta(days=15), qstart + timedelta(days=15))
    if not series:
        return None
    val = series.get(qstart)
    if val is None:
        return None
    return (f"Real GDP Q{q} {qy} ({ev.ref['estimate']} estimate): {val:+.1f}% q/q SAAR "
            "(BEA via FRED, current vintage).")


def _monthly_mm(series_id: str, y: int, m: int) -> float | None:
    """m/m % change of a monthly FRED series for month (y, m)."""
    py, pm = prev_month(y, m)
    series = _fred_series(series_id, Date(py, pm, 1) - timedelta(days=7), Date(y, m, 1) + timedelta(days=7))
    if not series:
        return None
    cur, prior = series.get(Date(y, m, 1)), series.get(Date(py, pm, 1))
    return None if cur is None or prior is None else (cur / prior - 1) * 100


def _pce(ev: Event) -> str | None:
    y, m = ev.ref["year"], ev.ref["month"]
    h, c = _monthly_mm("PCEPI", y, m), _monthly_mm("PCEPILFE", y, m)
    if h is None:
        return None
    return (f"PCE price index {month_name(y, m)}: {h:+.1f}% m/m"
            + (f"; core {c:+.1f}% m/m" if c is not None else "")
            + " (BEA via FRED, current vintage).")


def _retail(ev: Event) -> str | None:
    y, m = ev.ref["year"], ev.ref["month"]
    h, ex = _monthly_mm("RSAFS", y, m), _monthly_mm("RSFSXMV", y, m)
    if h is None:
        return None
    return (f"Retail sales {month_name(y, m)}: {h:+.1f}% m/m"
            + (f"; ex-autos {ex:+.1f}% m/m" if ex is not None else "")
            + " (Census via FRED, current vintage).")


def _durables(ev: Event) -> str | None:
    y, m = ev.ref["year"], ev.ref["month"]
    h = _monthly_mm("DGORDER", y, m)
    if h is None:
        return None
    return f"Durable goods orders {month_name(y, m)}: {h:+.1f}% m/m (Census via FRED, current vintage)."


def _ecb(ev: Event) -> str | None:
    decision = ev.ref["decision"]
    series = _fred_series("ECBDFR", decision - timedelta(days=10), decision + timedelta(days=14))
    if not series:
        return None
    before = _value_on_or_before(series, decision)
    after = _value_on_or_before(series, decision + timedelta(days=12))
    if before is None or after is None:
        return None
    (_, b), (after_day, a) = before, after
    if a == b:
        if after_day < decision + timedelta(days=8):
            return None  # ECB changes take effect ~a week later; data inconclusive
        return f"ECB held the deposit facility rate at {a:.2f}%."
    verb, bp = ("cut" if a < b else "raised"), abs(a - b) * 100
    return f"ECB {verb} the deposit facility rate {bp:.0f}bp to {a:.2f}%."


def _auction(ev: Event) -> str | None:
    r = ev.ref["record"]
    try:
        high_yield, btc = float(r["highYield"]), float(r["bidToCoverRatio"])
    except (KeyError, ValueError, TypeError):
        return None  # results not posted yet
    reopen = " reopening" if ev.ref["reopen"] else ""
    try:
        amount = f", ${float(r['offeringAmount']) / 1e9:.0f}B"
    except (KeyError, ValueError, TypeError):
        amount = ""
    return (f"Treasury {ev.ref['term']}-year {ev.ref['kind']}{reopen}: "
            f"high yield {high_yield:.3f}%, bid-to-cover {btc:.2f}{amount}.")


_SUMMARIZERS = {
    "CPI": _cpi, "PPI": _ppi, "NFP": _nfp, "JOBLESS_CLAIMS": _claims,
    "FOMC": _fomc, "GDP": _gdp, "PCE": _pce,
    "RETAIL_SALES": _retail, "DURABLE_GOODS": _durables, "ECB": _ecb,
}


def summarize(ev: Event) -> str:
    """Summary for an event that already happened; falls back to descriptive text."""
    text = None
    fn = _SUMMARIZERS.get(ev.sym) or (_auction if ev.sym.startswith("AUCTION_") else None)
    if fn is not None:
        try:
            text = fn(ev)
        except Exception as e:
            print(f"warning: summarizing {ev.sym} failed: {e}", file=sys.stderr)
    return text or ev.summary_fallback or f"{ev.name}."
