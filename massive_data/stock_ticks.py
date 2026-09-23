"""Shared, bounded-memory conversion for Massive stock tick flat files."""

import csv
import gzip
import io
import subprocess
import time
import zlib
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
import pyarrow as pa
import pyarrow.csv as pc
import pyarrow.parquet as pq

S3_ENDPOINT = "https://files.massive.com"
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SAMPLE_BYTES = 1024 * 1024
BLOCK_SIZE = 8 * 1024 * 1024


def sample_csv(compressed: bytes) -> io.BytesIO:
    """Recover complete CSV lines from a gzip prefix (including gzip members)."""
    chunks = []
    complete = False
    while compressed:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        chunks.append(decoder.decompress(compressed))
        complete = decoder.eof
        compressed = decoder.unused_data
    data = b"".join(chunks)
    if not complete:
        # Stock tick records occupy one line; the last one may be truncated.
        data = data[: data.rfind(b"\n") + 1]
    return io.BytesIO(data)


def convert_csv(source, path: Path, column_types: dict) -> tuple[int, pl.DataFrame]:
    """Stream CSV to Parquet, then check row count, schema and a read-back sample."""
    header = next(csv.reader([source.readline().decode("utf-8-sig")]))
    if len(header) != len(set(header)) or not {"ticker", "sip_timestamp"} <= set(header):
        raise ValueError("Invalid stock tick CSV header")
    # Unknown future columns remain strings rather than relying on first-block inference.
    types = {name: column_types.get(name, pa.string()) for name in header}
    rows = 0
    preview = None
    progress_time = time.monotonic()
    with pc.open_csv(
        source,
        read_options=pc.ReadOptions(column_names=header, block_size=BLOCK_SIZE),
        convert_options=pc.ConvertOptions(
            column_types=types, null_values=[""], strings_can_be_null=True,
        ),
    ) as reader:
        schema = reader.schema
        with pq.ParquetWriter(path, schema, compression="zstd") as writer:
            for batch in reader:
                if not batch.num_rows:
                    continue
                if preview is None:
                    preview = pa.Table.from_batches([batch.slice(0, 5)])
                writer.write_batch(batch)
                rows += batch.num_rows
                if time.monotonic() - progress_time >= 30:
                    print(f"Converted {rows:,} rows...", flush=True)
                    progress_time = time.monotonic()
    if not rows:
        raise ValueError("The downloaded CSV contains no stock ticks")
    with pq.ParquetFile(path) as saved:
        if saved.metadata.num_rows != rows or saved.schema_arrow != schema:
            raise RuntimeError("Parquet row count or schema verification failed")
        actual = pa.Table.from_batches([next(saved.iter_batches(batch_size=preview.num_rows))])
        if not actual.equals(preview):
            raise RuntimeError("Parquet sample read-back verification failed")
    return rows, pl.from_arrow(preview)


def save_ticks(
    *, name: str, s3_bucket: str, column_types: dict,
    date: str, data_dir: str | None, write: bool, sample: bool,
    staging_dir: Path | None = None,
) -> pl.DataFrame:
    """Download and verify a day or a 1 MiB prefix; return five preview rows."""
    try:
        parsed_date = datetime.strptime(date, "%Y%m%d")
        if parsed_date.strftime("%Y%m%d") != date:
            raise ValueError
    except ValueError:
        raise ValueError("date must be a valid calendar date in YYYYMMDD format") from None
    formatted = parsed_date.strftime("%Y-%m-%d")
    s3_path = f"{s3_bucket}/{date[:4]}/{date[4:6]}/{formatted}.csv.gz"
    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    if sample:
        base = base / "_samples"
    path = base / name / f"{date}.parquet"
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)

    # A staging directory on the output filesystem allows an atomic final rename.
    if staging_dir is not None:
        staging_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{name}-{date}-", dir=staging_dir or (path.parent if write else None)) as tmp:
        downloaded = Path(tmp) / "source.csv.gz"
        if sample:
            bucket, key = s3_path.removeprefix("s3://").split("/", 1)
            command = [
                "aws", "s3api", "get-object", "--bucket", bucket, "--key", key,
                "--range", f"bytes=0-{SAMPLE_BYTES - 1}", str(downloaded),
            ]
        else:
            command = ["aws", "s3", "cp", s3_path, str(downloaded), "--only-show-errors"]
        print(f"Downloading {'sample of ' if sample else ''}{s3_path}", flush=True)
        result = subprocess.run(
            command + ["--endpoint-url", S3_ENDPOINT], capture_output=True, text=True,
        )
        if result.returncode:
            raise RuntimeError(f"S3 download failed: {result.stderr.strip()}")

        source = sample_csv(downloaded.read_bytes()) if sample else gzip.open(downloaded, "rb")
        staged = Path(tmp) / "verified.parquet"
        print(f"Converting {date} to Parquet...", flush=True)
        with source:
            rows, preview = convert_csv(source, staged, column_types)
        if write:
            staged.replace(path)
        print(f"Verified {rows:,} {'sample ' if sample else ''}rows; {preview.width} columns.")
        print(f"Saved {path}" if write else "No output saved; pass --write to save.")
        print(preview)
    return preview
