# Save stock data
fetch_prices.sh provides an example how to download using massive s3. I'd like to have a script that do the following

1. The input is a date range, e.g., 20230101-20231231
2. Download the stock data day_aggs_v1
3. Unzip and load the file
4. Download split and dividend data with reference https://massive.com/docs/rest/stocks/corporate-actions/splits and  https://massive.com/docs/rest/stocks/corporate-actions/dividends
5. Add split and dividend to the file
6. Convert the file to parquet
7. save it to /Users/yichenchen/workspace/data/ref_stock_data in the format of YYYYMMDD.parquet


### API Details

**Splits API:** `GET https://api.polygon.io/v3/reference/splits`
- Parameters: `ticker`, `execution_date`, `execution_date.gte`, `execution_date.lte`
- Response fields: `execution_date`, `split_from`, `split_to`, `ticker`

**Dividends API:** `GET https://api.polygon.io/v3/reference/dividends`
- Parameters: `ticker`, `ex_dividend_date`, `ex_dividend_date.gte`, `ex_dividend_date.lte`
- Response fields: `ex_dividend_date`, `cash_amount`, `ticker`

### Implementation Approach

For each date in range:
1. Download day_aggs_v1 from S3 (existing)
2. Fetch splits for that date via REST API
3. Fetch dividends for that date via REST API
4. Join splits/dividends to price data by ticker
5. Save combined parquet with columns: `split_ratio`, `dividend_amount`

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

    # Fetch corporate actions for this date
    splits = GET /v3/reference/splits?execution_date={date}
    dividends = GET /v3/reference/dividends?ex_dividend_date={date}

    # Join to price data
    df = df.join(splits, on="ticker", how="left")
    df = df.join(dividends, on="ticker", how="left")

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
- `requests` — for REST API calls to fetch splits/dividends
- `POLYGON_API_KEY` environment variable required for REST API

### File Structure

```
ref_stock_data/
├── download_stock_data.py   # The one script
├── requirements.txt
└── plan.md
```

No utils. No config files. No classes. Just a script that does the job.
