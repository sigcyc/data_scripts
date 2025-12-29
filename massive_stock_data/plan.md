# Save stock data
fetch_prices.sh provides an example how to download using massive s3. I'd like to have a script that do the following

1. The input is a date range, e.g., 20230101-20231231
2. Download the stock data day_aggs_v1
3. Unzip and load the file
4. Convert the file to parquet
5. save it to /Users/yichenchen/workspace/data/ref_stock_data in the format of YYYYMMDD.parquet

---

## Implementation Plan

### Single Script: `download_stock_data.py`

One script. One purpose. No abstractions.

**Usage:**
```bash
python download_stock_data.py 20230101 20231231
```

### Core Logic (pseudocode)

```
for each date in range:
    s3_path = f"s3://flatfiles/us_stocks_sip/day_aggs_v1/{year}/{month}/{date}.csv.gz"
    download via aws s3 cp --endpoint-url https://files.massive.com
    read csv.gz directly with polars (handles decompression)
    write to /Users/yichenchen/workspace/data/ref_stock_data/{YYYYMMDD}.parquet
    delete temp csv.gz
```

### Key Decisions

1. **Polars over Pandas** — faster, handles gzip natively, writes parquet efficiently
2. **No temp file needed** — polars can read gzipped CSV directly from bytes or stream
3. **Skip existing files** — don't re-download if parquet already exists
4. **Fail fast** — if a download fails, log and continue to next date

### Dependencies

- `polars` (already in requirements.txt)
- `boto3` or subprocess `aws` CLI — CLI is simpler, already works per fetch_prices.sh

### File Structure

```
ref_stock_data/
├── download_stock_data.py   # The one script
├── requirements.txt
└── plan.md
```

No utils. No config files. No classes. Just a script that does the job.
