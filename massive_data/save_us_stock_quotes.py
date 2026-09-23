#!/usr/bin/env python3
"""Download Massive US stock quotes and convert to Parquet in bounded batches."""

from pathlib import Path

import pyarrow as pa
import typer

if __package__:
    from .stock_ticks import save_ticks
else:
    from stock_ticks import save_ticks

NAME = Path(__file__).stem.removeprefix("save_")
S3_BUCKET = "s3://flatfiles/us_stocks_sip/quotes_v1"
COLUMN_TYPES = {
    "ticker": pa.string(),
    "ask_exchange": pa.int64(),
    "ask_price": pa.float64(),
    "ask_size": pa.float64(),
    "bid_exchange": pa.int64(),
    "bid_price": pa.float64(),
    "bid_size": pa.float64(),
    "conditions": pa.string(),
    "indicators": pa.string(),
    "participant_timestamp": pa.int64(),
    "sequence_number": pa.int64(),
    "sip_timestamp": pa.int64(),
    "tape": pa.int64(),
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
