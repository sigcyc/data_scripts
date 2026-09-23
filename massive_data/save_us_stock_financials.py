#!/usr/bin/env python3
"""Download all available Massive US-stock statements, keeping the first ticker as sym."""

import argparse
import gzip
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

import polars as pl
import requests

API_BASE = "https://api.massive.com"
ENDPOINTS = {
    "income_statement": "/stocks/financials/v1/income-statements",
    "balance_sheet": "/stocks/financials/v1/balance-sheets",
    "cash_flow_statement": "/stocks/financials/v1/cash-flow-statements",
}
RATIOS_ENDPOINT = "/stocks/financials/v1/ratios"


class MassiveClient:
    def __init__(self, api_key: str, cache_dir: Path, refresh: bool = False,
                 cache_only: bool = False):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.cache_only = cache_only
        self.retrieval_log = []

    def fetch(self, endpoint: str, params: dict) -> list[dict]:
        identity = json.dumps([endpoint, params], sort_keys=True)
        cache = self.cache_dir / (hashlib.sha256(identity.encode()).hexdigest() + ".json.gz")
        if cache.exists() and not self.refresh:
            with gzip.open(cache, "rt") as source:
                rows = json.load(source)
            self.retrieval_log.append({
                "endpoint": endpoint, "params": params, "cache_hit": True,
                "cache_file": str(cache.resolve()), "rows": len(rows),
                "cache_modified_at": datetime.fromtimestamp(cache.stat().st_mtime, timezone.utc).isoformat(),
            })
            return rows
        if self.cache_only:
            raise RuntimeError(f"Cached response missing for {endpoint}: {cache.name}")
        original_params = dict(params)
        url = API_BASE + endpoint
        rows = []
        seen = set()
        while url:
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.netloc not in ("api.massive.com", "api.polygon.io"):
                raise RuntimeError("API pagination returned an unexpected host")
            if url in seen:
                raise RuntimeError("API pagination loop detected")
            seen.add(url)
            for attempt in range(6):
                try:
                    response = self.session.get(url, params=params, timeout=(15, 90))
                except requests.RequestException:
                    if attempt == 5:
                        raise RuntimeError(f"Network request failed for {endpoint}") from None
                    time.sleep(min(2 ** attempt, 30))
                    continue
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 5:
                    retry = response.headers.get("Retry-After", "")
                    delay = float(retry) if retry.isdigit() else 2 ** attempt
                    time.sleep(min(delay, 60))
                    continue
                if not response.ok:
                    raise RuntimeError(f"Massive HTTP {response.status_code} for {endpoint}; check account access")
                break
            body = response.json()
            if body.get("status") != "OK" or not isinstance(body.get("results"), list):
                raise RuntimeError(f"Unexpected Massive response for {endpoint}")
            rows.extend(body["results"])
            url = body.get("next_url")
            params = None
        cache.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=cache.parent, suffix=".tmp", delete=False) as tmp:
            staged = Path(tmp.name)
        try:
            with gzip.open(staged, "wt") as target:
                json.dump(rows, target)
            staged.replace(cache)
        finally:
            staged.unlink(missing_ok=True)
        self.retrieval_log.append({
            "endpoint": endpoint, "params": original_params, "cache_hit": False,
            "cache_file": str(cache.resolve()), "rows": len(rows),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        })
        return rows


def source_records_frame(records: list[dict]) -> pl.DataFrame:
    """Convert source objects to columns, rejecting any changed values."""
    frame = pl.from_dicts(records, infer_schema_length=None, strict=True)
    for source, row in zip(records, frame.iter_rows(named=True), strict=True):
        for name, value in source.items():
            if row[name] != value:
                raise ValueError(f"Parquet conversion changes source field {name}")
    return frame


def write_parquet(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=".", suffix=".parquet", delete=False) as tmp:
        staged = Path(tmp.name)
    try:
        frame.write_parquet(staged, compression="zstd")
        actual = pl.read_parquet(staged)
        if not frame.equals(actual):
            raise RuntimeError(f"Parquet read-back verification failed for {path.name}")
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", "--output-dir", type=Path, default=Path("/Volumes/ssd"),
                        help="Parent directory for the three statement datasets")
    parser.add_argument("--cache-dir", type=Path, default=Path(__file__).parent / ".financials_cache")
    parser.add_argument("--refresh", action="store_true", help="Fetch fresh API responses instead of using cached responses")
    parser.add_argument("--cache-only", action="store_true", help="Use cached responses without network requests")
    parser.add_argument("--write", action="store_true", help="Save one Parquet file per statement type")
    arguments = parser.parse_args(argv)
    if arguments.cache_only and arguments.refresh:
        parser.error("--cache-only and --refresh cannot be used together")
    key = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
    if not key and not arguments.cache_only:
        parser.error("Set MASSIVE_API_KEY or POLYGON_API_KEY")
    client = MassiveClient(key or "", arguments.cache_dir,
                           refresh=arguments.refresh, cache_only=arguments.cache_only)
    for name, endpoint in ENDPOINTS.items():
        records = client.fetch(endpoint, {"limit": 50000, "sort": "period_end.asc"})
        if not records:
            raise RuntimeError(f"No records returned for {endpoint}; existing file was not replaced")
        frame = source_records_frame(records)
        frame = frame.with_columns(pl.col("tickers").list.first()).rename({"tickers": "sym"})
        output = arguments.data_dir / f"us_stock_financials_{name}" / "part0.parquet"
        if arguments.write:
            write_parquet(frame, output)
        action = f"Saved {output}" if arguments.write else "Preview only; pass --write to save"
        print(f"{name}: {frame.height:,} records. {action}", flush=True)


if __name__ == "__main__":
    main()
