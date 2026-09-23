# massive_data

Downloads US stock market data from Massive S3 and financial data from Massive REST APIs, saving Parquet files.

## Scripts

- **`save_us_stock_day.py`** — Daily aggregates. Downloads from S3, enriches with splits/dividends/ticker types from Polygon API.
- **`save_us_stock_min1.py`** — 1-minute aggregates. Downloads from S3.
- **`save_us_stock_trades.py`** / **`save_us_stock_quotes.py`** — Tick flat files,
  converted in bounded batches by `stock_ticks.py`. Default to `workspace/data`;
  `--sample` verifies a 1 MiB prefix and writes under `_samples` when `--write` is set.
- **`save_us_stock_financials.py`** — All available US-stock financial statement records;
  requests each endpoint without date or universe filters. Saves `part0.parquet` in
  `us_stock_financials_income_statement`, `us_stock_financials_balance_sheet`,
  and `us_stock_financials_cash_flow_statement` under `/Volumes/ssd`
  (override with `--data-dir`). One row per API result; `tickers` is replaced with
  its first element as the string column `sym`. All other source values are preserved.
  Shares API, conversion, and file-writing helpers with the ratios script.
  Use `--refresh --write` to replace each complete statement file.
- **`save_us_stock_ratios.py`** — All available Massive ratio snapshots under
  `/Volumes/ssd/us_stock_ratios`, grouped by source trading `date`. Uses shared
  source-preservation helpers from `save_us_stock_financials.py`.

## Usage

Single date (typer CLI):
```bash
python save_us_stock_day.py --date 20230101 --write
python save_us_stock_min1.py --date 20230101 --write
```

Date range via `save_data` skill:
```bash
/save_data us_stock_day 20230101-20231231
/save_data us_stock_min1 20230101-20231231
```

## Data Sources

- **S3**: `s3://flatfiles/us_stocks_sip/{day_aggs_v1,minute_aggs_v1,trades_v1,quotes_v1}/` via AWS CLI at `https://files.massive.com`
- **Polygon API** (`api.polygon.io`): splits, dividends, ticker types/references

## Environment

- `POLYGON_API_KEY` env var required for daily script (splits/dividends/ticker enrichment)
- AWS CLI configured for S3 access
- Dependencies: `polars`, `pyarrow`, `requests`, `typer`, `cyc` (internal lib for aggregates)

## Architecture

- Aggregate scripts download to `/tmp/`, convert to parquet, and clean up temp files
- Tick scripts stream conversion and verify Parquet before an atomic rename;
  staging files live beside the output with `--write`, otherwise in a temporary directory
- Ticker metadata cached to `/tmp/polygon_tickers.parquet`
- Aggregate output defaults to `get_data_dir() / {name} / {date}.parquet`;
  tick output defaults to `workspace/data / {name} / {date}.parquet`, both overridable via `--data-dir`
