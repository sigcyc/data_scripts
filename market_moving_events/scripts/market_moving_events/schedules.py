"""Event schedule generators.

Each generator takes a target date and returns the events falling on that date.

Date sources, in order of preference:
- "official": embedded calendars published far ahead (FOMC/ECB/BOJ meetings,
  Treasury refunding statements), index-methodology dates (third-Friday
  rebalances, expirations, ...), and TreasuryDirect-announced auctions.
- "fred": exact past+future release dates from the FRED `release/dates` API,
  used for BLS/BEA/Census releases when a FRED api key is configured (free at
  https://fred.stlouisfed.org/docs/api/api_key.html; put it in $FRED_API_KEY or
  config/fred_api_key.txt).
- "rule": calendar approximations used when no FRED key is available. Usually
  right within a couple of days for CPI/PPI/GDP/PCE/retail and exact for the
  rest; consumers can filter on schedule_source if they need confirmed dates.
"""
from __future__ import annotations

import json
import sys
from datetime import date as Date, timedelta
from functools import lru_cache
import os
from pathlib import Path

from .base import (
    Event,
    at_et,
    is_session,
    last_bday,
    last_weekday,
    month_name,
    next_session,
    nth_bday,
    nth_weekday,
    prev_month,
    prev_session,
)
from . import http_cache

# ---------------------------------------------------------------------------
# Central banks: official meeting calendars (published 1-2 years in advance).
# Extend these tables when next year's calendars are published.
# ---------------------------------------------------------------------------
# FOMC (day1, day2); statement 14:00 ET on day2, press conference 14:30 ET.
FOMC_MEETINGS = [
    ("2024-01-30", "2024-01-31"), ("2024-03-19", "2024-03-20"),
    ("2024-04-30", "2024-05-01"), ("2024-06-11", "2024-06-12"),
    ("2024-07-30", "2024-07-31"), ("2024-09-17", "2024-09-18"),
    ("2024-11-06", "2024-11-07"), ("2024-12-17", "2024-12-18"),
    ("2025-01-28", "2025-01-29"), ("2025-03-18", "2025-03-19"),
    ("2025-05-06", "2025-05-07"), ("2025-06-17", "2025-06-18"),
    ("2025-07-29", "2025-07-30"), ("2025-09-16", "2025-09-17"),
    ("2025-10-28", "2025-10-29"), ("2025-12-09", "2025-12-10"),
    ("2026-01-27", "2026-01-28"), ("2026-03-17", "2026-03-18"),
    ("2026-04-28", "2026-04-29"), ("2026-06-16", "2026-06-17"),
    ("2026-07-28", "2026-07-29"), ("2026-09-15", "2026-09-16"),
    ("2026-10-27", "2026-10-28"), ("2026-12-08", "2026-12-09"),
]
FOMC_YEARS = {2024, 2025, 2026}

# ECB Governing Council monetary policy decision days (statement 14:15 CET =
# 08:15 ET, press conference 08:45 ET).
ECB_DECISIONS = [
    "2025-01-30", "2025-03-06", "2025-04-17", "2025-06-05",
    "2025-07-24", "2025-09-11", "2025-10-30", "2025-12-18",
    "2026-02-05", "2026-03-19", "2026-04-30", "2026-06-11",
    "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17",
]
ECB_YEARS = {2025, 2026}

# BOJ monetary policy meeting second (decision) days, JST. The decision lands
# around midday JST = ~22:30-01:30 ET during the prior US evening, so the event
# is emitted on the prior ET date at 23:00 (time approximate by nature).
BOJ_DECISIONS_JST = [
    "2025-01-24", "2025-03-19", "2025-05-01", "2025-06-17",
    "2025-07-31", "2025-09-19", "2025-10-30", "2025-12-19",
    "2026-01-23", "2026-03-19", "2026-04-28", "2026-06-16",
    "2026-07-31", "2026-09-18", "2026-10-30", "2026-12-18",
]
BOJ_YEARS = {2025, 2026}


def fomc_events(d: Date) -> list[Event]:
    events = []
    if d.year not in FOMC_YEARS:
        print(f"warning: no FOMC calendar embedded for {d.year}; extend FOMC_MEETINGS", file=sys.stderr)
    for day1_s, day2_s in FOMC_MEETINGS:
        day1, day2 = Date.fromisoformat(day1_s), Date.fromisoformat(day2_s)
        if d == day2:
            name = "FOMC rate decision (statement 14:00 ET, press conference 14:30 ET)"
            if day2.month in (3, 6, 9, 12):  # quarterly meetings include projections
                name += " — includes Summary of Economic Projections (dot plot)"
            events.append(Event(
                at_et(d, 14, 0), "FOMC", name,
                schedule_source="official", ref={"day1": day1, "day2": day2},
                summary_fallback="FOMC statement released at 14:00 ET.",
            ))
        # minutes: three weeks after the decision, 14:00 ET (moved up if holiday)
        minutes = day2 + timedelta(days=21)
        if not is_session(minutes):
            minutes = prev_session(minutes)
        if d == minutes:
            events.append(Event(
                at_et(d, 14, 0), "FOMC_MINUTES", f"FOMC minutes of the {month_name(day2.year, day2.month)} meeting",
                schedule_source="rule",
                summary_fallback=f"Minutes of the {month_name(day2.year, day2.month)} FOMC meeting released at 14:00 ET.",
            ))

    # Jackson Hole: Fed Chair's keynote, Friday morning of the KC Fed symposium
    # (held Thu-Sat of the week of the 4th Friday of August; 2024-2026 all match).
    if d.month == 8 and d == nth_weekday(d.year, 8, 4, 4):
        events.append(Event(
            at_et(d, 10, 0), "JACKSON_HOLE",
            "Jackson Hole symposium — Fed Chair keynote (~10:00 ET; exact time set days ahead)",
            schedule_source="rule",
            summary_fallback="Fed Chair spoke at the Jackson Hole economic symposium.",
        ))
    return events


def intl_cb_events(d: Date) -> list[Event]:
    events = []
    if d.year not in ECB_YEARS or d.year not in BOJ_YEARS:
        print(f"warning: no ECB/BOJ calendar embedded for {d.year}; extend the tables", file=sys.stderr)
    if d.isoformat() in ECB_DECISIONS:
        events.append(Event(
            at_et(d, 8, 15), "ECB", "ECB rate decision (statement 08:15 ET / 14:15 CET, press conference 08:45 ET)",
            schedule_source="official", ref={"decision": d},
            summary_fallback="ECB monetary policy decision released at 08:15 ET.",
        ))
    next_day = (d + timedelta(days=1)).isoformat()
    if next_day in BOJ_DECISIONS_JST:
        events.append(Event(
            at_et(d, 23, 0), "BOJ",
            "Bank of Japan rate decision (overnight ET, ~23:00-01:30; time approximate)",
            schedule_source="official",
            summary_fallback="Bank of Japan policy decision announced overnight ET (midday JST).",
        ))
    return events


# ---------------------------------------------------------------------------
# Index events: S&P 500 (SPY), Nasdaq-100 (QQQ), MSCI, Russell, triple witching.
# Effective dates follow published index methodology; announcement dates follow
# the providers' usual conventions (approximate by nature).
# ---------------------------------------------------------------------------
def _russell_june_recon(year: int) -> Date:
    # fourth Friday of June (FTSE Russell convention), holiday-shifted
    return prev_session(nth_weekday(year, 6, 4, 4))


def index_events(d: Date) -> list[Event]:
    events = []
    y, m = d.year, d.month

    if m in (3, 6, 9, 12):
        # S&P quarterly rebalance: announced after the close around the first
        # Friday; effective at the close of the third Friday (prior session if
        # that Friday is a holiday, e.g. Juneteenth June 2026) = triple witching.
        if d == nth_weekday(y, m, 4, 1):
            events.append(Event(
                at_et(d, 17, 15), "SPY_REBAL_ANNOUNCE",
                "S&P 500 quarterly rebalance announcement (S&P DJI press release after close)",
                summary_fallback="S&P DJI announced quarterly index changes after the close (see spglobal.com).",
            ))
        eff = prev_session(nth_weekday(y, m, 4, 3))
        if d == eff:
            events.append(Event(
                at_et(d, 16, 0), "SPY_REBAL_EFFECTIVE",
                "S&P 500 quarterly rebalance effective at the close",
                schedule_source="official",
                summary_fallback="S&P 500 quarterly rebalance: tracking funds trade at today's close.",
            ))
            events.append(Event(
                at_et(d, 16, 0), "TRIPLE_WITCHING",
                "Triple witching: stock index futures, index options and stock options expire",
                schedule_source="official",
                summary_fallback="Quarterly triple-witching expiration; elevated volume into the close.",
            ))

    if m == 12:
        # Nasdaq-100 annual reconstitution: announced after the close on the
        # second Friday of December, effective at the open of the Monday after
        # the third Friday (tracking funds trade at the prior close).
        if d == nth_weekday(y, 12, 4, 2):
            events.append(Event(
                at_et(d, 20, 0), "QQQ_RECON_ANNOUNCE",
                "Nasdaq-100 annual reconstitution announcement (after close)",
                summary_fallback="Nasdaq announced annual Nasdaq-100 reconstitution after the close (see nasdaq.com).",
            ))
        eff = prev_session(nth_weekday(y, 12, 4, 3))
        if d == eff:
            events.append(Event(
                at_et(d, 16, 0), "QQQ_RECON_EFFECTIVE",
                "Nasdaq-100 reconstitution: changes effective next open; tracking funds trade at this close",
                schedule_source="official",
                summary_fallback="Nasdaq-100 reconstitution trades at today's close, effective at the next open.",
            ))

    if m in (2, 5, 8, 11):
        # MSCI quarterly/semi-annual index review. Results are released around
        # 23:00 CET (~17:00 ET) typically on the second Tuesday of the review
        # month; changes are effective as of the close of the last business day.
        if d == nth_weekday(y, m, 1, 2):
            events.append(Event(
                at_et(d, 17, 0), "MSCI_REVIEW_ANNOUNCE",
                "MSCI index review announcement (~23:00 CET; date approximate)",
                summary_fallback="MSCI announced index review results (see msci.com/index-review).",
            ))
        if d == last_bday(y, m):
            events.append(Event(
                at_et(d, 16, 0), "MSCI_REVIEW_EFFECTIVE",
                "MSCI index review changes effective at the close",
                schedule_source="official",
                summary_fallback="MSCI index review rebalance: tracking funds trade at today's close.",
            ))

    # Russell reconstitution: semi-annual since 2026 (June + December).
    if m in (5, 6):
        recon = _russell_june_recon(y)
        # preliminary add/delete lists: posted after 18:00 ET five Fridays
        # before reconstitution (May 22 2026, May 23 2025)
        if d == recon - timedelta(days=35):
            events.append(Event(
                at_et(d, 18, 0), "RUSSELL_PRELIM",
                "Russell reconstitution preliminary add/delete lists (after 18:00 ET)",
                summary_fallback="FTSE Russell posted preliminary reconstitution lists (lseg.com/russell-reconstitution).",
            ))
        if d == recon:
            events.append(Event(
                at_et(d, 16, 0), "RUSSELL_RECON",
                "Russell indexes reconstitution effective at the close (June)",
                schedule_source="official",
                summary_fallback="Russell reconstitution: rebalance trades in today's closing auction.",
            ))
    if m == 12 and y >= 2026:
        # December semi-annual reconstitution: second Friday of December
        # (Dec 11 2026 per FTSE Russell schedule update, Nov 2025)
        if d == prev_session(nth_weekday(y, 12, 4, 2)):
            events.append(Event(
                at_et(d, 16, 0), "RUSSELL_RECON",
                "Russell indexes semi-annual reconstitution effective at the close (December)",
                schedule_source="official",
                summary_fallback="Russell semi-annual reconstitution: rebalance trades in today's closing auction.",
            ))

    return events


# ---------------------------------------------------------------------------
# Flow / expiration fixtures (pure calendar methodology).
# ---------------------------------------------------------------------------
def flow_events(d: Date) -> list[Event]:
    events = []
    y, m = d.year, d.month

    # monthly options expiration (third Friday); quarterly months are covered
    # by TRIPLE_WITCHING instead
    if m not in (3, 6, 9, 12) and d == prev_session(nth_weekday(y, m, 4, 3)):
        events.append(Event(
            at_et(d, 16, 0), "OPEX", "Monthly options expiration (third Friday)",
            schedule_source="official",
            summary_fallback="Monthly option expiration; elevated volume into the close.",
        ))

    # VIX expiration: 30 days before the next month's standard SPX expiration
    # (third Friday, holiday-adjusted); settlement (SOQ) prints off the open
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    vix = prev_session(nth_weekday(ny, nm, 4, 3)) - timedelta(days=30)
    if not is_session(vix):
        vix = prev_session(vix)
    if d == vix:
        events.append(Event(
            at_et(d, 9, 30), "VIX_EXP",
            "VIX futures/options expiration (settlement value from SPX opening prints)",
            schedule_source="official",
            summary_fallback="VIX expiration: settlement printed off the SPX open.",
        ))

    # quarter-end: pension/target-allocation rebalance flows at the close
    if m in (3, 6, 9, 12) and d == last_bday(y, m):
        events.append(Event(
            at_et(d, 16, 0), "QUARTER_END", "Quarter-end close (rebalance flows, window dressing)",
            schedule_source="official",
            summary_fallback="Quarter-end close; month/quarter-end rebalance flows.",
        ))

    # US general election: even years, Tuesday after the first Monday of November
    if m == 11 and y % 2 == 0 and d == nth_weekday(y, 11, 0, 1) + timedelta(days=1):
        kind = "presidential" if y % 4 == 0 else "midterm"
        events.append(Event(
            at_et(d, 20, 0), "US_ELECTION", f"US {kind} election day (results overnight)",
            schedule_source="official",
            summary_fallback=f"US {kind} elections held; results drove the overnight session.",
        ))

    return events


# ---------------------------------------------------------------------------
# FRED release/dates: exact release schedules (needs a free api key).
# Release names are verified once per fetch so a wrong id can never emit dates.
# ---------------------------------------------------------------------------
FRED_RELEASES = {
    "CPI": (10, "consumer price index"),
    "PPI": (46, "producer price index"),
    "NFP": (50, "employment situation"),
    "GDP": (53, "gross domestic product"),
    "PCE": (54, "personal income"),
    "JOLTS": (192, "job openings"),
    "RETAIL": (9, "advance monthly sales"),
}


@lru_cache(maxsize=1)
def fred_api_key() -> str | None:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        return key
    key_file = Path(__file__).resolve().parents[2] / "config" / "fred_api_key.txt"
    if key_file.exists():
        return key_file.read_text().strip() or None
    return None


def _fred_release_name_ok(release: str, key: str) -> bool:
    rid, expected = FRED_RELEASES[release]
    url = f"https://api.stlouisfed.org/fred/release?release_id={rid}&api_key={key}&file_type=json"
    text = http_cache.get_text(f"fred_release_{rid}.json", url, ttl_hours=24 * 30)
    if text is None:
        return False
    try:
        name = json.loads(text)["releases"][0]["name"]
    except (KeyError, IndexError, ValueError):
        return False
    if expected not in name.lower():
        print(f"warning: FRED release {rid} is '{name}', expected ~'{expected}'; ignoring", file=sys.stderr)
        return False
    return True


@lru_cache(maxsize=None)
def fred_release_dates(release: str, year: int) -> frozenset[Date] | None:
    """All release dates (past and scheduled) for the release around `year`."""
    key = fred_api_key()
    if not key or not _fred_release_name_ok(release, key):
        return None
    rid, _ = FRED_RELEASES[release]
    url = (
        "https://api.stlouisfed.org/fred/release/dates"
        f"?release_id={rid}&api_key={key}&file_type=json"
        f"&include_release_dates_with_no_data=true&sort_order=asc&limit=2000"
        f"&realtime_start={year - 1}-01-01&realtime_end={year + 1}-12-31"
    )
    text = http_cache.get_text(f"fred_reldates_{release}_{year}.json", url, ttl_hours=24)
    if text is None:
        return None
    try:
        dates = frozenset(Date.fromisoformat(rd["date"]) for rd in json.loads(text)["release_dates"])
    except (KeyError, ValueError) as e:
        print(f"warning: bad FRED release/dates payload for {release}: {e}", file=sys.stderr)
        return None
    return dates


def _on_fred_schedule(release: str, d: Date) -> bool | None:
    """True/False when the FRED schedule is available, None when it is not."""
    dates = fred_release_dates(release, d.year)
    return None if dates is None else d in dates


def _fred_date_in_month(release: str, year: int, month: int) -> Date | None:
    dates = fred_release_dates(release, Date(year, month, 1).year)
    if dates is None:
        return None
    in_month = [x for x in dates if x.year == year and x.month == month]
    return min(in_month) if in_month else None


# ---------------------------------------------------------------------------
# BLS releases: CPI, PPI, Employment Situation — 08:30 ET.
# ---------------------------------------------------------------------------
def _rule_cpi(year: int, month: int) -> Date:
    # CPI lands around the 10th-15th; approximate with first session on/after the 10th
    return next_session(Date(year, month, 10))


def _rule_ppi(year: int, month: int) -> Date:
    # PPI is usually released within a couple of days of CPI
    return next_session(_rule_cpi(year, month) + timedelta(days=1))


def _rule_nfp(year: int, month: int) -> Date:
    # Employment Situation: third Friday after the reference week (the week
    # containing the 12th of the prior month), shifted off holidays; the
    # year-opening report slips a week (data processing around New Year).
    ry, rm = prev_month(year, month)
    ref_day = Date(ry, rm, 12)
    ref_saturday = ref_day + timedelta(days=(5 - ref_day.weekday()) % 7)
    release = ref_saturday + timedelta(days=20)
    if release.month == 1 and release.day <= 5:
        release += timedelta(days=7)
    return prev_session(release)


def _nfp_date(year: int, month: int) -> Date | None:
    return _fred_date_in_month("NFP", year, month) or (
        _rule_nfp(year, month) if fred_release_dates("NFP", year) is None else None
    )


def bls_release_events(d: Date) -> list[Event]:
    ry, rm = prev_month(d.year, d.month)
    ref = month_name(ry, rm)
    specs = [
        ("CPI", "Consumer Price Index", _rule_cpi),
        ("PPI", "Producer Price Index (final demand)", _rule_ppi),
        ("NFP", "Employment Situation (nonfarm payrolls, unemployment rate)", _rule_nfp),
    ]
    events = []
    for sym, name, rule in specs:
        fred = _on_fred_schedule(sym, d)
        if fred is True:
            source = "fred"
        elif fred is None and d == rule(d.year, d.month):
            source = "rule"
        else:
            continue
        events.append(Event(
            at_et(d, 8, 30), sym, f"{name} for {ref}, 08:30 ET",
            release_for=ref, schedule_source=source, ref={"year": ry, "month": rm},
            summary_fallback=f"{name} for {ref} released at 08:30 ET (actuals unavailable).",
        ))
    return events


# ---------------------------------------------------------------------------
# BEA releases: GDP and PCE (personal income & outlays) — 08:30 ET.
# ---------------------------------------------------------------------------
def _rule_gdp(year: int, month: int) -> Date:
    # GDP estimates come at month-end (last Thursday), pulled forward in December
    if month == 12:
        return prev_session(Date(year, 12, 23))
    return prev_session(last_weekday(year, month, 3))


def _rule_pce(year: int, month: int) -> Date:
    if month == 12:
        return prev_session(Date(year, 12, 22))
    return prev_session(last_weekday(year, month, 4))


def bea_release_events(d: Date) -> list[Event]:
    events = []

    fred = _on_fred_schedule("GDP", d)
    if fred is True or (fred is None and d == _rule_gdp(d.year, d.month)):
        q = (d.month - 1) // 3 or 4
        qy = d.year if d.month > 3 else d.year - 1
        estimate = ("advance", "second", "third")[(d.month - 1) % 3]
        events.append(Event(
            at_et(d, 8, 30), "GDP", f"GDP Q{q} {qy} ({estimate} estimate), 08:30 ET",
            release_for=f"Q{q} {qy}", schedule_source="fred" if fred else "rule",
            ref={"q": q, "qy": qy, "estimate": estimate},
            summary_fallback=f"BEA GDP release (Q{q} {qy}, {estimate} estimate) at 08:30 ET.",
        ))

    fred = _on_fred_schedule("PCE", d)
    if fred is True or (fred is None and d == _rule_pce(d.year, d.month)):
        ry, rm = prev_month(d.year, d.month)
        ref = month_name(ry, rm)
        events.append(Event(
            at_et(d, 8, 30), "PCE", f"Personal income & outlays for {ref} (PCE price index), 08:30 ET",
            release_for=ref, schedule_source="fred" if fred else "rule", ref={"year": ry, "month": rm},
            summary_fallback=f"PCE price index for {ref} released at 08:30 ET (actuals unavailable).",
        ))

    # JOLTS only when the exact schedule is available (no reliable simple rule)
    if _on_fred_schedule("JOLTS", d):
        ry, rm = prev_month(*prev_month(d.year, d.month))
        ref = month_name(ry, rm)
        events.append(Event(
            at_et(d, 10, 0), "JOLTS", f"JOLTS job openings for {ref}, 10:00 ET",
            release_for=ref, schedule_source="fred",
            summary_fallback=f"JOLTS report for {ref} released at 10:00 ET.",
        ))

    return events


# ---------------------------------------------------------------------------
# Other macro releases: retail sales, ADP, UMich, durable goods, ECI,
# Conference Board confidence.
# ---------------------------------------------------------------------------
def other_macro_events(d: Date) -> list[Event]:
    events = []
    y, m = d.year, d.month
    ry, rm = prev_month(y, m)
    prev_ref = month_name(ry, rm)
    cur_ref = month_name(y, m)

    # retail sales (Census MARTS): ~mid-month, 08:30
    fred = _on_fred_schedule("RETAIL", d)
    if fred is True or (fred is None and d == next_session(Date(y, m, 15))):
        events.append(Event(
            at_et(d, 8, 30), "RETAIL_SALES", f"Advance retail sales for {prev_ref}, 08:30 ET",
            release_for=prev_ref, schedule_source="fred" if fred else "rule",
            ref={"year": ry, "month": rm},
            summary_fallback=f"Advance retail sales for {prev_ref} released at 08:30 ET (actuals unavailable).",
        ))

    # ADP national employment: the Wednesday before the jobs report, 08:15
    nfp = _nfp_date(y, m)
    if nfp is not None:
        adp = nfp - timedelta(days=(nfp.weekday() - 2) % 7 or 7)
        if d == prev_session(adp):
            events.append(Event(
                at_et(d, 8, 15), "ADP", f"ADP private employment for {prev_ref}, 08:15 ET",
                release_for=prev_ref,
                summary_fallback=f"ADP private payrolls report for {prev_ref} released at 08:15 ET.",
            ))

    # University of Michigan consumer sentiment: preliminary ~2nd Friday,
    # final ~last Friday, both 10:00 (includes inflation expectations)
    if d == prev_session(nth_weekday(y, m, 4, 2)):
        events.append(Event(
            at_et(d, 10, 0), "UMICH_PRELIM",
            f"U. Michigan consumer sentiment for {cur_ref} (preliminary, incl. inflation expectations), 10:00 ET",
            release_for=cur_ref,
            summary_fallback=f"U. Michigan preliminary sentiment for {cur_ref} released at 10:00 ET.",
        ))
    if d == prev_session(last_weekday(y, m, 4)):
        events.append(Event(
            at_et(d, 10, 0), "UMICH_FINAL",
            f"U. Michigan consumer sentiment for {cur_ref} (final), 10:00 ET",
            release_for=cur_ref,
            summary_fallback=f"U. Michigan final sentiment for {cur_ref} released at 10:00 ET.",
        ))

    # durable goods orders (Census advance report): ~25th-27th, 08:30
    if d == next_session(Date(y, m, 25)):
        events.append(Event(
            at_et(d, 8, 30), "DURABLE_GOODS", f"Durable goods orders for {prev_ref} (advance), 08:30 ET",
            release_for=prev_ref, ref={"year": ry, "month": rm},
            summary_fallback=f"Durable goods orders for {prev_ref} released at 08:30 ET (actuals unavailable).",
        ))

    # Employment Cost Index: last business day of Jan/Apr/Jul/Oct, 08:30
    if m in (1, 4, 7, 10) and d == last_bday(y, m):
        q = {1: 4, 4: 1, 7: 2, 10: 3}[m]
        qy = y - 1 if m == 1 else y
        events.append(Event(
            at_et(d, 8, 30), "ECI", f"Employment Cost Index Q{q} {qy}, 08:30 ET",
            release_for=f"Q{q} {qy}",
            summary_fallback=f"Employment Cost Index for Q{q} {qy} released at 08:30 ET.",
        ))

    # Conference Board consumer confidence: last Tuesday of the month, 10:00
    if d == prev_session(last_weekday(y, m, 1)):
        events.append(Event(
            at_et(d, 10, 0), "CB_CONFIDENCE", f"Conference Board consumer confidence for {cur_ref}, 10:00 ET",
            release_for=cur_ref,
            summary_fallback=f"Conference Board consumer confidence for {cur_ref} released at 10:00 ET.",
        ))

    return events


# ---------------------------------------------------------------------------
# Weekly / monthly fixtures with reliable rules.
# ---------------------------------------------------------------------------
def recurring_events(d: Date) -> list[Event]:
    events = []

    # initial jobless claims: Thursdays 08:30 ET (Wednesday when Thursday is a holiday)
    claims_day = None
    if d.weekday() == 3 and is_session(d) and not (d.month == 11 and d.day == 11):
        claims_day = d  # Veterans Day: NYSE trades but DOL is closed, release moves up
    elif d.weekday() == 2:
        thursday = d + timedelta(days=1)
        if not is_session(thursday) or (thursday.month == 11 and thursday.day == 11):
            claims_day = d
    if claims_day:
        week_ending = d - timedelta(days=(d.weekday() - 5) % 7)  # prior Saturday
        events.append(Event(
            at_et(d, 8, 30), "JOBLESS_CLAIMS",
            f"Initial jobless claims (week ending {week_ending}), 08:30 ET",
            release_for=str(week_ending), ref={"week_ending": week_ending},
            summary_fallback="Weekly initial jobless claims released at 08:30 ET.",
        ))

    # ISM PMIs: manufacturing on the 1st business day, services on the 3rd, 10:00 ET
    ry, rm = prev_month(d.year, d.month)
    ref = month_name(ry, rm)
    if d == nth_bday(d.year, d.month, 1):
        events.append(Event(
            at_et(d, 10, 0), "ISM_MFG", f"ISM Manufacturing PMI for {ref}, 10:00 ET",
            release_for=ref, summary_fallback=f"ISM Manufacturing PMI for {ref} released at 10:00 ET.",
        ))
    if d == nth_bday(d.year, d.month, 3):
        events.append(Event(
            at_et(d, 10, 0), "ISM_SVC", f"ISM Services PMI for {ref}, 10:00 ET",
            release_for=ref, summary_fallback=f"ISM Services PMI for {ref} released at 10:00 ET.",
        ))

    return events


# ---------------------------------------------------------------------------
# Treasury supply: coupon auctions (TreasuryDirect API) and the quarterly
# refunding statement.
# ---------------------------------------------------------------------------
# Confirmed refunding-statement dates (08:30 ET, Wednesdays). Too irregular for
# a rule (Jan 28-Feb 5 etc.); each statement names the next date — keep current.
QRA_DATES = [
    "2025-02-05", "2025-04-30", "2025-07-30", "2025-11-05",
    "2026-02-04", "2026-05-06", "2026-08-05",
]

AUCTION_TERMS = {"2-Year", "3-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year"}


@lru_cache(maxsize=1)
def _treasury_auctions() -> dict[Date, list[dict]]:
    """Coupon auctions by date: ~2 years back (with results) plus all announced."""
    by_date: dict[Date, list[dict]] = {}
    seen = set()
    for kind, url in [
        ("announced", "https://www.treasurydirect.gov/TA_WS/securities/announced?format=json"),
        ("auctioned_note", "https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&days=750&type=Note"),
        ("auctioned_bond", "https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&days=750&type=Bond"),
    ]:
        text = http_cache.get_text(f"td_{kind}.json", url, ttl_hours=2)
        if text is None:
            continue
        try:
            records = json.loads(text)
        except ValueError:
            print(f"warning: bad TreasuryDirect payload ({kind})", file=sys.stderr)
            continue
        for r in records:
            if r.get("type") not in ("Note", "Bond") or r.get("originalSecurityTerm") not in AUCTION_TERMS:
                continue
            day = Date.fromisoformat(r["auctionDate"][:10])
            key = (day, r.get("cusip"))
            if key in seen:  # announced+auctioned overlap; auctioned (results) wins
                continue
            seen.add(key)
            by_date.setdefault(day, []).append(r)
    return by_date


def treasury_events(d: Date) -> list[Event]:
    events = []

    if d.isoformat() in QRA_DATES:
        events.append(Event(
            at_et(d, 8, 30), "QRA", "Treasury quarterly refunding statement (auction sizes), 08:30 ET",
            schedule_source="official",
            summary_fallback="Treasury quarterly refunding statement released (coupon auction sizes).",
        ))

    for r in _treasury_auctions().get(d, []):
        term = r["originalSecurityTerm"].split("-")[0]
        reopen = " reopening" if r.get("reopening") == "Yes" else ""
        kind = "note" if r["type"] == "Note" else "bond"
        try:
            amount = f"${float(r['offeringAmount']) / 1e9:.0f}B"
        except (ValueError, TypeError):
            amount = "size TBA"
        events.append(Event(
            at_et(d, 13, 0), f"AUCTION_{term}Y",
            f"Treasury {term}-year {kind}{reopen} auction ({amount}), results ~13:02 ET",
            schedule_source="official",
            ref={"record": r, "term": term, "kind": kind, "reopen": bool(reopen)},
            summary_fallback=f"Treasury {term}-year {kind} auction completed at 13:00 ET.",
        ))
    return events


def events_for(d: Date) -> list[Event]:
    return [
        *fomc_events(d),
        *intl_cb_events(d),
        *index_events(d),
        *flow_events(d),
        *bls_release_events(d),
        *bea_release_events(d),
        *other_macro_events(d),
        *recurring_events(d),
        *treasury_events(d),
    ]
