# massive_stock_data

Downloads US stock OHLCV data from Massive S3 (`files.massive.com`) and saves as parquet files.

## Scripts

- **`save_stock_data_day.py`** — Daily aggregates. Downloads from S3, enriches with splits/dividends/ticker types from Polygon API.
- **`save_stock_data_min1.py`** — 1-minute aggregates. Downloads from S3.

## Usage

Single date (typer CLI):
```bash
python save_stock_data_day.py --date 20230101 --write
python save_stock_data_min1.py --date 20230101 --write
```

Date range via `save_data` skill:
```bash
/save_data stock_data_day 20230101-20231231
/save_data stock_data_min1 20230101-20231231
```

## Data Sources

- **S3**: `s3://flatfiles/us_stocks_sip/{day_aggs_v1,minute_aggs_v1}/` via `aws s3 cp --endpoint-url https://files.massive.com`
- **Polygon API** (`api.polygon.io`): splits, dividends, ticker types/references

## Environment

- `POLYGON_API_KEY` env var required for daily script (splits/dividends/ticker enrichment)
- AWS CLI configured for S3 access
- Dependencies: `polars`, `requests`, `typer`, `cyc` (internal lib)

## Architecture

- Downloads to `/tmp/`, converts to parquet, cleans up temp files
- Ticker metadata cached to `/tmp/polygon_tickers.parquet`
- Output defaults to `get_data_dir() / {name} / {date}.parquet`, overridable via `--data-dir`
