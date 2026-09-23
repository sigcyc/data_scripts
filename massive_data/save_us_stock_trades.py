#!/usr/bin/env python3
"""Download Massive US stock trades and convert to Parquet in bounded batches."""

from pathlib import Path

import pyarrow as pa
import typer

if __package__:
    from .stock_ticks import save_ticks
else:
    from stock_ticks import save_ticks

NAME = Path(__file__).stem.removeprefix("save_")
S3_BUCKET = "s3://flatfiles/us_stocks_sip/trades_v1"
COLUMN_TYPES = {
    "ticker": pa.string(),
    "conditions": pa.string(),
    "correction": pa.int64(),
    "exchange": pa.int64(),
    "id": pa.string(),
    "participant_timestamp": pa.int64(),
    "price": pa.float64(),
    "sequence_number": pa.int64(),
    "sip_timestamp": pa.int64(),
    # Since February 2026, flat-file sizes can contain six fractional digits.
    "size": pa.decimal128(38, 6),
    "tape": pa.int64(),
    "trf_id": pa.int64(),
    "trf_timestamp": pa.int64(),
}


def main(
    date: str = "20260326",
    data_dir: str | None = None,
    write: bool = False,
    sample: bool = False,
):
    """Use --sample to verify only the first 1 MiB; --write saves verified Parquet."""
    df = save_ticks(
        name=NAME, s3_bucket=S3_BUCKET, column_types=COLUMN_TYPES,
        date=date, data_dir=data_dir, write=write, sample=sample,
    )
    if not write:
        globals().update(locals())


if __name__ == "__main__":
    typer.run(main)
