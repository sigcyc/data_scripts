#!/usr/bin/env python3
"""Build quarterly Form 13F holdings datasets from SEC structured data.

For each quarter-end report period (e.g. 20250331) this downloads the SEC
Form 13F data set zip covering that period's filing window, merges the member
files (INFOTABLE + COVERPAGE + SUBMISSION), de-duplicates amendments, resolves
CUSIPs to ticker symbols via OpenFIGI, and writes data/YYYYMMDD.parquet.

Source: https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets

Usage:
    python save_form13f.py 2025                 # all quarters of 2025
    python save_form13f.py 2025q1               # one quarter
    python save_form13f.py 20250331 20250630    # explicit period end dates
    python save_form13f.py 2025 --force         # rebuild even if output exists
"""

import argparse
import calendar
import os
import re
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import requests

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "cache" / "raw"
CUSIP_CACHE = ROOT / "cache" / "cusip_ticker.parquet"

def _load_env() -> None:
    """Load KEY=VALUE lines from .env (real environment wins)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, _, v = line.strip().partition("=")
            if k and not k.startswith("#") and k not in os.environ:
                os.environ[k] = v.strip().strip("'\"")


_load_env()
SEC_BASE = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/"
SEC_HEADERS = {"User-Agent": os.environ.get("SEC_USER_AGENT", "form13f-dataset simonchen1992@gmail.com")}
FIGI_URL = "https://api.openfigi.com/v3/mapping"
FIGI_KEY = os.environ.get("OPENFIGI_API_KEY", "")

EARLIEST_PERIOD = date(2013, 3, 31)  # data sets start with filings received 2013 Q2


# ---------------------------------------------------------------- periods

def quarter_ends(year: int) -> list[date]:
    return [date(year, 3, 31), date(year, 6, 30), date(year, 9, 30), date(year, 12, 31)]


def parse_targets(args: list[str]) -> list[date]:
    """Each arg is a year (2025), a quarter (2025q1), or a period end date (20250331)."""
    periods = set()
    for a in args:
        a = a.strip().lower()
        if re.fullmatch(r"\d{4}", a):
            periods.update(quarter_ends(int(a)))
        elif m := re.fullmatch(r"(\d{4})q([1-4])", a):
            periods.add(quarter_ends(int(m[1]))[int(m[2]) - 1])
        elif re.fullmatch(r"\d{8}", a):
            try:
                d = date(int(a[:4]), int(a[4:6]), int(a[6:]))
            except ValueError:
                d = None
            if d is None or d not in quarter_ends(d.year):
                sys.exit(f"error: {a} is not a quarter end date")
            periods.add(d)
        else:
            sys.exit(f"error: cannot parse target {a!r} (use YYYY, YYYYqN or YYYYMMDD)")

    today = date.today()
    out = []
    for p in sorted(periods):
        if p < EARLIEST_PERIOD:
            print(f"{p:%Y%m%d}: skipped, SEC data sets start at {EARLIEST_PERIOD:%Y%m%d}")
        elif p >= today:
            print(f"{p:%Y%m%d}: skipped, period not over yet")
        else:
            out.append(p)
    return out


def zip_name(period: date) -> str:
    """SEC zip covering the filing window for a report period (due 45 days after period end).

    Through period 2023-09-30 the sets are named by receipt calendar quarter
    (period 2023-06-30 -> 2023q3_form13f.zip). From period 2023-12-31 on, SEC
    switched to 3-month windows aligned with 13F due dates (e.g. period
    2025-03-31 -> 01mar2025-31may2025_form13f.zip).
    """
    y = period.year
    if period <= date(2023, 9, 30):
        return f"{y + 1}q1_form13f.zip" if period.month == 12 else f"{y}q{period.month // 3 + 1}_form13f.zip"
    if period == date(2023, 12, 31):
        return "01jan2024-29feb2024_form13f.zip"
    windows = {3: f"01mar{y}-31may{y}", 6: f"01jun{y}-31aug{y}", 9: f"01sep{y}-30nov{y}"}
    if period.month in windows:
        return f"{windows[period.month]}_form13f.zip"
    feb_end = 29 if calendar.isleap(y + 1) else 28
    return f"01dec{y}-{feb_end}feb{y + 1}_form13f.zip"


# ---------------------------------------------------------------- download

def download_zip(period: date) -> Path | None:
    name = zip_name(period)
    dest = RAW_DIR / name
    if dest.exists():
        return dest
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    url = SEC_BASE + name
    print(f"{period:%Y%m%d}: downloading {url}", flush=True)
    r = requests.get(url, headers=SEC_HEADERS, stream=True, timeout=(10, 900))
    if r.status_code in (403, 404):
        print(f"{period:%Y%m%d}: {name} not available on SEC site yet (HTTP {r.status_code})")
        return None
    r.raise_for_status()
    tmp = dest.with_suffix(".part")
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    return dest


def read_tsv(zf: zipfile.ZipFile, member: str) -> pl.DataFrame:
    # some quarters nest the files in a folder inside the zip, some don't
    name = next((n for n in zf.namelist() if n.rsplit("/", 1)[-1].upper() == member.upper()), None)
    if name is None:
        raise FileNotFoundError(f"{member} not found in {zf.filename}: {zf.namelist()}")
    return pl.read_csv(
        zf.read(name),
        separator="\t",
        quote_char=None,
        encoding="utf8-lossy",
        infer_schema=False,
        truncate_ragged_lines=True,
    )


# ---------------------------------------------------------------- amendments

def effective_accessions(filings: pl.DataFrame) -> set[str]:
    """Pick, per manager, the accessions that together represent final holdings.

    A RESTATEMENT amendment (or amendment with unspecified type) replaces every
    earlier filing for the period; NEW HOLDINGS amendments add to it. The base
    filing is therefore the last original/restatement, and everything after it
    is additive.
    """
    keep: set[str] = set()
    for _, g in filings.group_by("CIK"):
        rows = g.sort(["filing_date", "amendment_no", "ACCESSION_NUMBER"]).to_dicts()
        base = 0
        for i, r in enumerate(rows):
            if not r["is_amendment"] or r["amendment_type"] != "NEW HOLDINGS":
                base = i
        keep.update(r["ACCESSION_NUMBER"] for r in rows[base:])
    return keep


# ---------------------------------------------------------------- tickers

def _load_cache() -> dict[str, dict]:
    if not CUSIP_CACHE.exists():
        return {}
    df = pl.read_parquet(CUSIP_CACHE)
    if "figi_ticker" not in df.columns:  # migrate pre-figi_ticker caches
        df = df.with_columns(figi_ticker=pl.col("ticker"))
    # rows mapped before figi_ticker existed had their non-equity (bond)
    # ticker discarded; drop them so they are re-queried with it kept
    df = df.filter(pl.col("ticker").is_not_null() | pl.col("name").is_null()
                   | pl.col("figi_ticker").is_not_null())
    return {r["cusip"]: r for r in df.to_dicts()}


def _save_cache(cache: dict[str, dict]) -> None:
    CUSIP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    schema = {"cusip": pl.Utf8, "ticker": pl.Utf8, "figi_ticker": pl.Utf8, "name": pl.Utf8,
              "security_type": pl.Utf8, "market_sector": pl.Utf8, "exch_code": pl.Utf8,
              "mapped_at": pl.Utf8}
    df = pl.DataFrame(list(cache.values()), schema=schema)
    if CUSIP_CACHE.exists():  # merge so concurrent runs don't clobber each other
        old = pl.read_parquet(CUSIP_CACHE)
        if "figi_ticker" not in old.columns:
            old = old.with_columns(figi_ticker=pl.col("ticker"))
        df = pl.concat([old.select(df.columns), df]).unique(subset="cusip", keep="last")
    tmp = CUSIP_CACHE.with_suffix(".tmp.parquet")
    df.write_parquet(tmp)
    tmp.rename(CUSIP_CACHE)


def _figi_post(jobs: list[dict], headers: dict) -> list[dict]:
    for _ in range(6):
        r = requests.post(FIGI_URL, headers=headers, json=jobs, timeout=60)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After") or 20) + 2)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("OpenFIGI: still rate-limited after 6 retries")


def _figi_result(cusip: str, job: dict, pass_no: int) -> dict | None:
    d = (job.get("data") or [None])[0]
    if d is None:
        return None
    # second pass has no exchange filter: accept equities only, so bond
    # tickers like "AAPL 2.4 05/03/23" don't pollute the ticker column;
    # figi_ticker keeps the raw value for underlying-symbol derivation
    ticker = d["ticker"] if pass_no == 1 or d.get("marketSector") == "Equity" else None
    return {"cusip": cusip, "ticker": ticker, "figi_ticker": d["ticker"], "name": d.get("name"),
            "security_type": d.get("securityType"), "market_sector": d.get("marketSector"),
            "exch_code": d.get("exchCode"), "mapped_at": str(date.today())}


def map_tickers(cusips: list[str], map_limit: int = 0) -> dict[str, dict]:
    """CUSIP -> cache record (ticker, figi_ticker, market_sector, ...) via
    OpenFIGI, with a persistent local cache.

    cusips should be ordered most-important-first: the cache is flushed as we
    go, so an interrupted run still keeps everything mapped so far.
    Letter-prefixed identifiers (foreign issuers) are CINS, not CUSIP.
    """
    cache = _load_cache()
    todo = [c for c in cusips if c not in cache]
    if map_limit and len(todo) > map_limit:
        todo = todo[:map_limit]
    if not todo:
        return cache

    batch, delay = (100, 0.3) if FIGI_KEY else (10, 2.5)
    headers = {"Content-Type": "application/json"} | ({"X-OPENFIGI-APIKEY": FIGI_KEY} if FIGI_KEY else {})
    est = len(todo) / batch * delay * 1.5
    print(f"mapping {len(todo)} new CUSIPs via OpenFIGI "
          f"({'with' if FIGI_KEY else 'NO'} API key, ~{est / 60:.0f} min)", flush=True)

    def run_pass(items: list[str], pass_no: int) -> list[str]:
        misses = []
        for i in range(0, len(items), batch):
            chunk = items[i:i + batch]
            jobs = [{"idType": "ID_CINS" if c[0].isalpha() else "ID_CUSIP", "idValue": c} for c in chunk]
            if pass_no == 1:
                for j in jobs:
                    j["exchCode"] = "US"
            for c, job in zip(chunk, _figi_post(jobs, headers)):
                if res := _figi_result(c, job, pass_no):
                    cache[c] = res
                else:
                    misses.append(c)
            done = i + len(chunk)
            if (i // batch) % 25 == 24:
                _save_cache(cache)
                print(f"  pass {pass_no}: {done}/{len(items)}", flush=True)
            time.sleep(delay)
        return misses

    misses = run_pass(todo, 1)  # US composite listing
    unmapped = run_pass(misses, 2) if misses else []  # any listing, equities only
    for c in unmapped:
        cache[c] = {"cusip": c, "ticker": None, "figi_ticker": None, "name": None,
                    "security_type": None, "market_sector": None, "exch_code": None,
                    "mapped_at": str(date.today())}
    _save_cache(cache)
    print(f"  mapped {len(todo) - len(unmapped)}/{len(todo)} new CUSIPs", flush=True)
    return cache


# ---------------------------------------------------------------- build

def build_period(period: date, data_dir: Path, force: bool, skip_tickers: bool, map_limit: int) -> None:
    out = data_dir / f"{period:%Y%m%d}.parquet"
    if out.exists() and not force:
        print(f"{out.name} already exists, skipping (use --force to rebuild)")
        return
    zip_path = download_zip(period)
    if zip_path is None:
        return

    with zipfile.ZipFile(zip_path) as zf:
        sub = read_tsv(zf, "SUBMISSION.tsv")
        cov = read_tsv(zf, "COVERPAGE.tsv")
        info = read_tsv(zf, "INFOTABLE.tsv")
        om2 = read_tsv(zf, "OTHERMANAGER2.tsv")

    period_str = period.strftime("%d-%b-%Y").upper()
    filings = (
        sub.filter(pl.col("PERIODOFREPORT") == period_str)
        .filter(pl.col("SUBMISSIONTYPE").str.strip_chars().is_in(["13F-HR", "13F-HR/A"]))
        .join(cov, on="ACCESSION_NUMBER", how="left")
        .with_columns(
            filing_date=pl.col("FILING_DATE").str.to_date("%d-%b-%Y"),
            is_amendment=pl.col("ISAMENDMENT") == "Y",
            amendment_no=pl.col("AMENDMENTNO").cast(pl.Int64, strict=False),
            amendment_type=pl.col("AMENDMENTTYPE").fill_null("").str.strip_chars(),
        )
    )
    if filings.is_empty():
        print(f"{period:%Y%m%d}: no 13F-HR filings found in {zip_path.name}")
        return

    keep = effective_accessions(filings)
    meta = filings.filter(pl.col("ACCESSION_NUMBER").is_in(keep)).select(
        "ACCESSION_NUMBER",
        pl.col("CIK").alias("cik"),
        pl.col("FILINGMANAGER_NAME").alias("manager_name"),
        "filing_date",
        pl.col("SUBMISSIONTYPE").alias("submission_type"),
        pl.col("REPORTTYPE").alias("report_type"),
        "is_amendment",
        "amendment_no",
        pl.col("amendment_type").replace("", None),
    )

    if "FIGI" not in info.columns:  # column added by SEC in mid-2023
        info = info.with_columns(FIGI=pl.lit(None, dtype=pl.Utf8))
    df = (
        info.join(meta, on="ACCESSION_NUMBER", how="inner")
        .with_row_index("__row")
    )
    # OTHERMANAGER holds cover-page sequence number(s), possibly several per
    # row ("1,5"); resolve them to names via the OTHERMANAGER2 lookup
    om_names = (
        df.select("__row", "ACCESSION_NUMBER",
                  seq=pl.col("OTHERMANAGER").str.extract_all(r"\d+"))
        .explode("seq")
        .drop_nulls("seq")
        .with_columns(pl.col("seq").cast(pl.Int64))
        .join(
            om2.select("ACCESSION_NUMBER",
                       seq=pl.col("SEQUENCENUMBER").cast(pl.Int64, strict=False),
                       om_name=pl.col("NAME").str.strip_chars(),
                       om_cik=pl.col("CIK").str.strip_chars()),
            on=["ACCESSION_NUMBER", "seq"], how="left",
        )
        .sort("seq")
        .group_by("__row")
        .agg(other_manager_names=pl.col("om_name").drop_nulls().str.join("; "),
             other_manager_ciks=pl.col("om_cik").drop_nulls().str.join("; "))
        .with_columns(pl.col("other_manager_names").replace("", None),
                      pl.col("other_manager_ciks").replace("", None))
    )
    df = (
        df.join(om_names, on="__row", how="left")
        .with_columns(
            cusip=pl.col("CUSIP").str.strip_chars().str.to_uppercase(),
            value=pl.col("VALUE").cast(pl.Float64, strict=False).round(0).cast(pl.Int64, strict=False),
            shares=pl.col("SSHPRNAMT").cast(pl.Float64, strict=False).round(0).cast(pl.Int64, strict=False),
            voting_sole=pl.col("VOTING_AUTH_SOLE").cast(pl.Float64, strict=False).cast(pl.Int64, strict=False),
            voting_shared=pl.col("VOTING_AUTH_SHARED").cast(pl.Float64, strict=False).cast(pl.Int64, strict=False),
            voting_none=pl.col("VOTING_AUTH_NONE").cast(pl.Float64, strict=False).cast(pl.Int64, strict=False),
        )
    )

    if skip_tickers:
        df = df.with_columns(deliverable_symbol=pl.lit(None, dtype=pl.Utf8),
                             underlying_symbol=pl.lit(None, dtype=pl.Utf8))
    else:
        by_value = (
            df.group_by("cusip").agg(pl.col("value").sum()).sort("value", descending=True)
        )["cusip"].drop_nulls().to_list()
        recs = map_tickers([c for c in by_value if c], map_limit)
        tick_df = pl.DataFrame(
            {"cusip": list(recs),
             "ticker": [r["ticker"] for r in recs.values()],
             "deliverable_symbol": [r.get("figi_ticker") for r in recs.values()],
             "market_sector": [r.get("market_sector") for r in recs.values()]},
            schema={"cusip": pl.Utf8, "ticker": pl.Utf8, "deliverable_symbol": pl.Utf8,
                    "market_sector": pl.Utf8},
        ).with_columns(
            # equities map to themselves; for corporate bonds and preferreds
            # the FIGI ticker starts with the issuer's equity symbol
            # ("BABA 0.5 06/01/31" -> BABA). Govt/Muni/Mtge have no equity
            # underlier, so they stay null.
            underlying_symbol=pl.coalesce(
                pl.col("ticker"),
                pl.when(pl.col("market_sector").is_in(["Corp", "Pfd"]))
                .then(pl.col("deliverable_symbol").str.extract(r"^([A-Z][A-Z0-9./]*)\s")),
            )
        ).drop("ticker", "market_sector")
        df = df.join(tick_df, on="cusip", how="left")

    df = df.select(
        period_of_report=pl.lit(period),
        cik="cik",
        manager_name="manager_name",
        filing_date="filing_date",
        submission_type="submission_type",
        report_type="report_type",
        is_amendment="is_amendment",
        amendment_no="amendment_no",
        amendment_type="amendment_type",
        accession_number="ACCESSION_NUMBER",
        issuer_name=pl.col("NAMEOFISSUER"),
        title_of_class=pl.col("TITLEOFCLASS"),
        cusip="cusip",
        figi="FIGI",
        deliverable_symbol="deliverable_symbol",
        underlying_symbol="underlying_symbol",
        value="value",
        shares="shares",
        shares_type=pl.col("SSHPRNAMTTYPE"),
        put_call=pl.col("PUTCALL"),
        investment_discretion=pl.col("INVESTMENTDISCRETION"),
        other_manager=pl.col("OTHERMANAGER"),
        other_manager_names="other_manager_names",
        other_manager_ciks="other_manager_ciks",
        voting_sole="voting_sole",
        voting_shared="voting_shared",
        voting_none="voting_none",
    ).sort(["cik", "value"], descending=[False, True])

    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.parquet")
    df.write_parquet(tmp, compression="zstd")
    tmp.rename(out)

    n_mgr = df["cik"].n_unique()
    cov_rows = df["underlying_symbol"].is_not_null().mean()
    val = df.select((pl.col("value").filter(pl.col("underlying_symbol").is_not_null()).sum()
                     / pl.col("value").sum()).alias("v"))["v"][0]
    print(f"{out.name}: {df.height:,} holdings, {n_mgr:,} managers, "
          f"symbol coverage {cov_rows:.1%} of rows / {(val or 0):.1%} of value", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", help="YYYY, YYYYqN or YYYYMMDD quarter end date")
    ap.add_argument("--force", action="store_true", help="rebuild even if the parquet exists")
    ap.add_argument("--skip-tickers", action="store_true", help="skip CUSIP->ticker mapping")
    ap.add_argument("--map-limit", type=int, default=0, help="map at most N new CUSIPs (for testing)")
    ap.add_argument("--data-dir", default=str(ROOT / "data"), help="output directory")
    args = ap.parse_args()

    periods = parse_targets(args.targets)
    if not periods:
        sys.exit("nothing to do")
    for p in periods:
        build_period(p, Path(args.data_dir), args.force, args.skip_tickers, args.map_limit)


if __name__ == "__main__":
    main()
