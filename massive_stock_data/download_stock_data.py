#!/usr/bin/env python3
"""Download stock data from S3 and convert to parquet."""

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

S3_ENDPOINT = "https://files.massive.com"
S3_BUCKET = "s3://flatfiles/us_stocks_sip/day_aggs_v1"
OUTPUT_DIR = Path("/Users/yichenchen/workspace/data/stock_data_day")


def date_range(start: str, end: str):
    """Yield dates from start to end (inclusive)."""
    current = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")
    while current <= end_dt:
        yield current
        current += timedelta(days=1)


def download_and_convert(date: datetime) -> bool:
    """Download one day's data and convert to parquet. Returns True on success."""
    output_file = OUTPUT_DIR / f"{date.strftime('%Y%m%d')}.parquet"
    if output_file.exists():
        print(f"Skip {date.date()} - already exists")
        return True

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
        df.write_parquet(output_file)
        print(f"Done {date.date()}")
    finally:
        tmp_file.unlink(missing_ok=True)

    return True


def main():
    if len(sys.argv) != 3:
        print("Usage: python download_stock_data.py YYYYMMDD YYYYMMDD")
        sys.exit(1)

    start, end = sys.argv[1], sys.argv[2]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    success, failed = 0, 0
    for date in date_range(start, end):
        if download_and_convert(date):
            success += 1
        else:
            failed += 1

    print(f"\nComplete: {success} succeeded, {failed} failed")


if __name__ == "__main__":
    main()
