#!/usr/bin/env python3
"""Download stock data from S3 and convert to parquet."""

import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import requests

from cyc.time_util import parse_dates

MAX_WORKERS = 16

S3_ENDPOINT = "https://files.massive.com"
S3_BUCKET = "s3://flatfiles/us_stocks_sip/day_aggs_v1"
OUTPUT_DIR = Path("/Users/yichenchen/workspace/data/stock_data_day")
API_BASE = "https://api.polygon.io"
API_KEY = os.environ.get("POLYGON_API_KEY", "")


def date_range(start: str, end: str):
    """Yield dates from start to end (inclusive)."""
    current = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    while current <= end_dt:
        yield current
        current += timedelta(days=1)


def fetch_splits(date: datetime) -> pl.DataFrame:
    """Fetch stock splits for a given date."""
    date_str = date.strftime("%Y-%m-%d")
    url = f"{API_BASE}/stocks/v1/splits"
    params = {"execution_date": date_str, "limit": 1000, "apiKey": API_KEY}
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        return pl.DataFrame({"ticker": [], "split": []})
    data = resp.json().get("results", [])
    if not data:
        return pl.DataFrame({"ticker": [], "split": []})
    return pl.DataFrame([
        {"ticker": r["ticker"], "split": r["split_to"] / r["split_from"]}
        for r in data
    ])


def fetch_dividends(date: datetime) -> pl.DataFrame:
    """Fetch dividends for a given date."""
    date_str = date.strftime("%Y-%m-%d")
    url = f"{API_BASE}/stocks/v1/dividends"
    params = {"ex_dividend_date": date_str, "limit": 1000, "apiKey": API_KEY}
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        return pl.DataFrame({"ticker": [], "dividend": []})
    data = resp.json().get("results", [])
    if not data:
        return pl.DataFrame({"ticker": [], "dividend": []})
    return pl.DataFrame([
        {"ticker": r["ticker"], "dividend": r["cash_amount"]}
        for r in data
    ])


def download_and_convert(date: datetime) -> bool:
    """Download one day's data and convert to parquet. Returns True on success."""
    output_file = OUTPUT_DIR / f"{date.strftime('%Y%m%d')}.parquet"
    s3_path = f"{S3_BUCKET}/{date.year}/{date.month:02d}/{date.strftime('%Y-%m-%d')}.csv.gz"
    tmp_file = Path(f"/tmp/{date.strftime('%Y-%m-%d')}.csv.gz")

    # Download
    result = subprocess.run(
        ["aws", "s3", "cp", s3_path, str(tmp_file), "--endpoint-url", S3_ENDPOINT],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"Failed {date.date()} - {result.stderr.decode().strip()}")
        return False

    # Convert and save
    try:
        df = pl.read_csv(tmp_file)

        # Fetch and join corporate actions
        splits_df = fetch_splits(date)
        dividends_df = fetch_dividends(date)

        if splits_df.height > 0:
            df = df.join(splits_df, on="ticker", how="left")
        else:
            df = df.with_columns(pl.lit(None).alias("split"))

        if dividends_df.height > 0:
            df = df.join(dividends_df, on="ticker", how="left")
        else:
            df = df.with_columns(pl.lit(None).alias("dividend"))

        df.write_parquet(output_file)
        print(f"Done {date.date()} (splits: {splits_df.height}, dividends: {dividends_df.height})")
    finally:
        tmp_file.unlink(missing_ok=True)

    return True


def main():
    if len(sys.argv) != 2:
        print("Usage: python download_stock_data.py YYYYMMDD-YYYYMMDD")
        sys.exit(1)

    if not API_KEY:
        print("Error: POLYGON_API_KEY environment variable not set")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    dates = [datetime.strptime(d, "%Y%m%d") for d in parse_dates(sys.argv[1])]
    success, failed = 0, 0

    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_and_convert, d): d for d in dates}
        for future in as_completed(futures):
            if future.result():
                success += 1
            else:
                failed += 1

    print(f"\nComplete: {success} succeeded, {failed} failed")


if __name__ == "__main__":
    main()
