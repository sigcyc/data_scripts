This folder is self-contained.

When editing files in this folder:
- Do not inspect or copy patterns from sibling data_scripts unless explicitly asked.
- Treat sibling scripts as unrelated legacy examples.
- Only use files in this directory and shared utilities imported by this script.
- Ask before modifying shared utilities.

# form13f

Builds quarterly SEC Form 13F institutional holdings datasets as
`data/YYYYMMDD.parquet`, one file per quarter-end report period, with
CUSIP->ticker symbols added via OpenFIGI.

## Saving data

When asked e.g. "save 13f data for year 2025":

```bash
python save_form13f.py 2025
```

Targets can be years (`2025`), quarters (`2025q1`), or period end dates
(`20250331`), in any mix. Runs are incremental: existing parquets are skipped
(`--force` rebuilds). Earliest available period is 20130331.

Notes:
- The OpenFIGI API key is stored in the gitignored `.env` file here and is
  loaded automatically; with it, CUSIP->ticker mapping takes ~2 min/quarter.
  Without a key the first build of a fresh quarter takes hours (~25 req/min),
  so run it in the background. The cache (`cache/cusip_ticker.parquet`)
  makes later quarters fast either way.
- A period's data set is published by SEC ~2.5 months after the filing
  deadline at the earliest; the script reports and skips unpublished periods.
- `--skip-tickers` builds the parquet with a null ticker column (fast);
  re-running with `--force` later fills tickers from/into the cache.

See README.md for schema and design details.
