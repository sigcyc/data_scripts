```bash
python save_us_stock_day.py --date 20210101 --write
python save_us_stock_min1.py --date 20210101 --write
```

Output: `{data_dir}/us_stock_day/{date}.parquet` and `{data_dir}/us_stock_min1/{date}.parquet`.

US stock trades and quotes use the same `--date`, `--data-dir`, and `--write`
options. Run these commands from this directory to verify small downloads first:

```bash
python save_us_stock_trades.py --date 20260326 --sample --write
python save_us_stock_quotes.py --date 20260326 --sample --write
```

`--sample` downloads only the first 1 MiB of compressed data and keeps complete
CSV records. These are file-prefix samples, not representative market samples.
They are saved separately to `{data_dir}/_samples/us_stock_{trades,quotes}/{date}.parquet`.
Omit `--sample` to download the complete daily file after sample verification:

```bash
python save_us_stock_trades.py --date 20260326 --write
python save_us_stock_quotes.py --date 20260326 --write
```

The two new scripts default to `workspace/data` next to this repository
(`/Users/yichenchen/workspace/data` in this checkout), independently of
`cyc.config.get_data_dir()`. Complete files are saved as
`{data_dir}/us_stock_trades/{date}.parquet` and
`{data_dir}/us_stock_quotes/{date}.parquet`. Use `--data-dir` to override the base.

Conversion streams gzip data in 8 MiB CSV batches into Zstandard-compressed
Parquet. It needs disk space for the compressed download and staged Parquet,
but does not hold a complete day in memory or create an uncompressed CSV.
Row count, schema, and five preview rows are checked before the final file is
atomically replaced. Temporary files are cleaned up on success or failure.
Without `--write`, the download and verification still run; only a five-row
Polars preview is retained as `df` for interactive use and no output is saved.

Nanosecond timestamps and sequence numbers remain 64-bit integers. Trade IDs,
conditions, and quote indicators remain strings. Trade sizes use decimal(38, 6)
to preserve fractional shares exactly; prices and quote sizes use Float64.
Empty CSV fields become nulls. New, unrecognized columns are retained as strings.

Install `requirements.txt` and configure AWS CLI with Massive flat-file S3
credentials. A `403 Forbidden` response requires checking those credentials and
the account's access to the requested dataset.

Sources: [trades](https://massive.com/docs/flat-files/stocks/trades),
[quotes](https://massive.com/docs/flat-files/stocks/quotes), and
[fractional trade sizes](https://www.massive.com/blog/massive-now-returns-fractional-share-precision).

### Resumable trades and quotes backfill

From the repository root, run both datasets chronologically from January 2022:

```bash
python3 -u massive_data/save_us_stock_ticks.py --start-date 20220101 --data-dir /Volumes/Expansion
```

The end date defaults to today; `--end-date YYYYMMDD` fixes an inclusive cutoff.
`--list-only` reports the available file count and compressed source size without
downloading. Files are listed from Massive, so holidays and weekends are skipped.
Output goes to `us_stock_trades/YYYYMMDD.parquet` and
`us_stock_quotes/YYYYMMDD.parquet` directly under the destination.

Interrupt with Ctrl-C or `kill -TERM PID` (the PID is printed at startup and stored
in `/Volumes/Expansion/.stock_ticks.lock`). Rerun the same command to resume.
Completed Parquet files are checked by footer and required columns, then skipped.
The interrupted day starts over; downloads do not resume at a byte offset.
Original gzip files exist only during processing and are deleted afterward.
After a forced termination, the next attempt removes abandoned files in the
runner's `.backfill_staging` directory. A file lock prevents duplicate backfills
to the same destination. Each file gets twenty attempts with waits increasing
from 10 to 60 seconds before the job stops (`--retries` overrides this);
low disk space also stops the job, preserving completed days.

To keep it running after closing the terminal:

```bash
nohup python3 -u massive_data/save_us_stock_ticks.py --start-date 20220101 --data-dir /Volumes/Expansion > massive_data/stock_ticks_backfill.log 2>&1 &
tail -f massive_data/stock_ticks_backfill.log
```

## Financial statements and ratios

Set `MASSIVE_API_KEY` or `POLYGON_API_KEY` locally, then run from the repository
root:

```bash
python3 massive_data/save_us_stock_financials.py --refresh --write
python3 massive_data/save_us_stock_ratios.py --write
```

| Dataset | Default path |
|---|---|
| Income statements | `/Volumes/ssd/us_stock_financials_income_statement/part0.parquet` |
| Balance sheets | `/Volumes/ssd/us_stock_financials_balance_sheet/part0.parquet` |
| Cash-flow statements | `/Volumes/ssd/us_stock_financials_cash_flow_statement/part0.parquet` |
| Latest available ratio snapshots | `/Volumes/ssd/us_stock_ratios/YYYYMMDD.parquet` |

The financials downloader requests each statement endpoint with `limit=50000`
and `sort=period_end.asc`, follows every `next_url`, and saves one `part0.parquet`
inside each endpoint's directory. It applies no date, ticker, volume, or timeframe
filters. Each source result becomes one row. The first element of `tickers` is
saved as the string column `sym`; the original `tickers` column is replaced.
All other source fields and values, including duplicate records, are preserved.
Optional fields absent from a row become null. All returned periods are stored
together; each endpoint has its own file and schema.

```python
import polars as pl

income = pl.read_parquet('/Volumes/ssd/us_stock_financials_income_statement/part0.parquet')
balance = pl.read_parquet('/Volumes/ssd/us_stock_financials_balance_sheet/part0.parquet')
cash_flow = pl.read_parquet('/Volumes/ssd/us_stock_financials_cash_flow_statement/part0.parquet')
snow_income = income.filter(pl.col('sym') == 'SNOW')
```

`filing_date` and `period_end` are retained as ordinary source columns.
`filing_date` means the most recent SEC filing containing the period's data,
which may repeat prior-year comparisons; it is not the first public-availability
date. `period_end` is the accounting period's ending date. `timeframe` identifies
quarterly, annual, or trailing-twelve-month records. Fiscal year and quarter are
the issuer's labels; annual records can carry quarter 4. Overlapping periods
should not be summed together. This endpoint does not provide a history of
exactly what investors knew on each date.

`--data-dir` (alias `--output-dir`) changes the statement files' destination.
`--write` atomically replaces each complete file; without it, the script fetches,
caches, and verifies the records without saving Parquet. `--refresh` bypasses
completed request caches. `--cache-only` requires cached responses for the exact
query and makes no network requests. `--cache-dir` changes the cache location.

Conversion checks every source value before replacing `tickers` with its first
element as `sym`. The written Parquet is read back before replacement. Original
JSON records, including the complete ticker lists, remain under `.financials_cache/`.

The ratios script saves latest available snapshots grouped by the source trading
`date`; it cannot backfill historical daily ratios. It retains `_source_endpoint`
and `_raw_json` columns and writes request metadata and checksums under
`_metadata/`. Its `--output-dir` sets the ratio directory, and `--sample` downloads
SNOW under `_samples/`. Ratios fetch fresh responses by default and support
`--cache-only`.

Field definitions: [income statements](https://massive.com/docs/rest/stocks/fundamentals/income-statements),
[balance sheets](https://massive.com/docs/rest/stocks/fundamentals/balance-sheets),
[cash flow](https://massive.com/docs/rest/stocks/fundamentals/cash-flow-statements),
and [ratios](https://massive.com/docs/rest/stocks/fundamentals/ratios).
