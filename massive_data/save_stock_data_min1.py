#!/usr/bin/env python3
"""Download minute stock data from S3 and convert to parquet."""

import subprocess
from pathlib import Path

import polars as pl
import typer

from cyc.config import get_data_dir

NAME = Path(__file__).stem.removeprefix("save_")

S3_ENDPOINT = "https://files.massive.com"
S3_BUCKET = "s3://flatfiles/us_stocks_sip/minute_aggs_v1"


def main(
    date: str = "20260326",
    data_dir: str | None = None,
    write: bool = False,
):
    formatted = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    s3_path = f"{S3_BUCKET}/{date[:4]}/{date[4:6]}/{formatted}.csv.gz"
    tmp_file = Path(f"/tmp/{formatted}_min1.csv.gz")

    result = subprocess.run(
        ["aws", "s3", "cp", s3_path, str(tmp_file), "--endpoint-url", S3_ENDPOINT],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"S3 download failed: {result.stderr.decode().strip()}")

    try:
        df = pl.read_csv(tmp_file, schema_overrides={"volume": pl.Float64})
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
