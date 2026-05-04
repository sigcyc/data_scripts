#!/usr/bin/env python3
"""Download daily stock data from S3 and convert to parquet."""

import os
import subprocess
from pathlib import Path

import polars as pl
import requests
import typer

from cyc.config import get_data_dir

NAME = Path(__file__).stem.removeprefix("save_")

S3_ENDPOINT = "https://files.massive.com"
S3_BUCKET = "s3://flatfiles/us_stocks_sip/day_aggs_v1"
API_BASE = "https://api.polygon.io"
API_KEY = os.environ.get("POLYGON_API_KEY", "")
TICKERS_CACHE_FILE = Path("/tmp/polygon_tickers.parquet")


def fetch_and_save_tickers():
    """Fetch all US stock tickers with types and save to temp file."""
    resp = requests.get(f"{API_BASE}/v3/reference/tickers/types", params={"apiKey": API_KEY}, timeout=30)
    type_map = {r["code"]: r["description"] for r in resp.json().get("results", [])} if resp.ok else {}

    tickers = []
    url = f"{API_BASE}/v3/reference/tickers"
    params = {"market": "stocks", "active": "true", "limit": 1000, "apiKey": API_KEY}

    while url:
        resp = requests.get(url, params=params, timeout=30)
        if not resp.ok:
            break
        data = resp.json()
        for r in data.get("results", []):
            type_code = r.get("type", "")
            tickers.append({"ticker": r["ticker"], "type": type_code, "type_desc": type_map.get(type_code, "")})
        url = data.get("next_url")
        params = {"apiKey": API_KEY} if url else {}

    df = pl.DataFrame(tickers) if tickers else pl.DataFrame({"ticker": [], "type": [], "type_desc": []})
    df.write_parquet(TICKERS_CACHE_FILE)
    print(f"Fetched {df.height} tickers")


def fetch_splits(date_str: str) -> pl.DataFrame:
    """Fetch stock splits for a given date (YYYY-MM-DD format)."""
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


def fetch_dividends(date_str: str) -> pl.DataFrame:
    """Fetch dividends for a given date (YYYY-MM-DD format)."""
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
    ]).group_by("ticker").agg(pl.col("dividend").sum())


def main(
    date: str = "20260326",
    data_dir: str | None = None,
    write: bool = False,
):
    if not API_KEY:
        raise RuntimeError("POLYGON_API_KEY environment variable not set")

    if not TICKERS_CACHE_FILE.exists():
        fetch_and_save_tickers()

    # Download from S3
    formatted = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    s3_path = f"{S3_BUCKET}/{date[:4]}/{date[4:6]}/{formatted}.csv.gz"
    tmp_file = Path(f"/tmp/{formatted}.csv.gz")

    result = subprocess.run(
        ["aws", "s3", "cp", s3_path, str(tmp_file), "--endpoint-url", S3_ENDPOINT],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"S3 download failed: {result.stderr.decode().strip()}")

    try:
        df = pl.read_csv(tmp_file, schema_overrides={"volume": pl.Float64}).with_columns(
            pl.lit(formatted).str.to_date().alias("date")
        )

        splits_df = fetch_splits(formatted)
        dividends_df = fetch_dividends(formatted)

        if splits_df.height > 0:
            df = df.join(splits_df, on="ticker", how="left")
        else:
            df = df.with_columns(pl.lit(None).alias("split"))

        if dividends_df.height > 0:
            df = df.join(dividends_df, on="ticker", how="left")
        else:
            df = df.with_columns(pl.lit(None).alias("dividend"))

        tickers_df = pl.read_parquet(TICKERS_CACHE_FILE)
        df = df.join(tickers_df, on="ticker", how="left")
    finally:
        tmp_file.unlink(missing_ok=True)

    base = Path(data_dir or get_data_dir())
    path = base / NAME / f"{date}.parquet"

    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
    else:
        globals().update(locals())


if __name__ == "__main__":
    typer.run(main)
