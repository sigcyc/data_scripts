#!/usr/bin/env python3
"""Download all available Massive ratio snapshots without changing source values."""

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

if __package__:
    from .save_us_stock_financials import MassiveClient, RATIOS_ENDPOINT, source_records_frame, write_parquet
else:
    from save_us_stock_financials import MassiveClient, RATIOS_ENDPOINT, source_records_frame, write_parquet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("/Volumes/ssd/us_stock_ratios"))
    parser.add_argument("--cache-dir", type=Path, default=Path(__file__).parent / ".financials_cache" / "all_ratios")
    parser.add_argument("--sample", action="store_true", help="Download SNOW only, under _samples/")
    parser.add_argument("--cache-only", action="store_true", help="Replay completed cached responses without network calls")
    parser.add_argument("--write", action="store_true", help="Save daily Parquet files and run metadata")
    args = parser.parse_args(argv)
    key = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
    if not key and not args.cache_only:
        parser.error("Set MASSIVE_API_KEY or POLYGON_API_KEY")
    client = MassiveClient(key or "", args.cache_dir, refresh=not args.cache_only, cache_only=args.cache_only)
    params = {"limit": 5000, "sort": "ticker.asc"}
    if args.sample:
        params["ticker"] = "SNOW"
    entries = client.fetch(RATIOS_ENDPOINT, params)
    if not entries:
        raise RuntimeError("Massive returned no ratio records; no files were written")
    frame = source_records_frame([
        {**entry, "_source_endpoint": RATIOS_ENDPOINT,
         "_raw_json": json.dumps(entry, separators=(",", ":"), allow_nan=False)}
        for entry in entries
    ])
    first = ["date", "ticker"]
    provenance = ["_source_endpoint", "_raw_json"]
    frame = frame.select(first + sorted(set(frame.columns) - set(first + provenance)) + provenance)
    if args.sample and frame["ticker"].unique().to_list() != ["SNOW"]:
        raise ValueError("Unexpected symbol in the SNOW sample response")
    metadata = {
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": RATIOS_ENDPOINT, "sample": args.sample,
        "rows": frame.height, "symbols": frame["ticker"].n_unique(),
        "rows_by_source_date": dict(sorted(Counter(frame["date"]).items())),
        "schema": {name: str(dtype) for name, dtype in frame.schema.items()},
        "source_requests": client.retrieval_log,
    }
    if args.write:
        output = args.output_dir / "_samples" if args.sample else args.output_dir
        files = []
        for (day,), daily in sorted(frame.partition_by("date", as_dict=True).items()):
            path = output / f"{date.fromisoformat(day):%Y%m%d}.parquet"
            write_parquet(daily, path)
            files.append({"file": path.name, "rows": daily.height,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if sum(item["rows"] for item in files) != frame.height:
            raise RuntimeError("Saved row count does not match the source response")
        metadata["files"] = files
        metadata_dir = output / "_metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        (metadata_dir / f"run-{run_id}.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"Saved {frame.height:,} records for {metadata['symbols']:,} symbols to {output}")
    else:
        print(f"{frame.height:,} records for {metadata['symbols']:,} symbols; pass --write to save")
    return frame, metadata


if __name__ == "__main__":
    main()
