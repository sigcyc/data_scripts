# market_moving_events

Daily dataset of **scheduled** market-moving events (no breaking news): one parquet
per calendar day, one row per event, written via the `save_data` skill interface.
Deep dive — code structure, per-event scheduling logic, data sources, caching,
failure behavior: [docs/architecture.html](docs/architecture.html) (open in a browser).

```bash
# one day (prints the frame without --write)
python scripts/save_market_moving_events.py --date 20260617

# write a range through the save_data batch runner (df_type: market_moving_events)
/save_data scripts/save_market_moving_events.py 20260601-20261231
```

Output: `<data_dir>/market_moving_events/YYYYMMDD.parquet` (default `/Volumes/ssd`, override
with `--data-dir`). Registered in `cyc/files/df_types.yaml` with the `all_days`
calendar so events on non-NYSE days (e.g. NFP on Good Friday) are not skipped.
Days without events produce an empty frame with the full schema.

The script can be run for **future** dates (rows are the expected schedule) and
re-run for past dates, where it fills `summarize` with what actually happened.

## Schema

| column            | meaning                                                                 |
| ----------------- | ----------------------------------------------------------------------- |
| `time`            | event time, tz-aware `America/New_York` (ns)                            |
| `sym`             | event code (below)                                                      |
| `event_name`      | human-readable description                                              |
| `release_for`     | reference period (e.g. `May 2026`, `Q1 2026`), when applicable          |
| `event_date_type` | `actual` if the event time had passed when the row was built, else `expected` |
| `summarize`       | what happened — filled for past events only                             |
| `schedule_source` | how the date was determined: `official` / `fred` / `rule`               |

## Events

Macro releases:

| sym | what | time (ET) | date source |
| --- | --- | --- | --- |
| `CPI` | Consumer Price Index | 08:30 | fred or rule |
| `PPI` | Producer Price Index, final demand | 08:30 | fred or rule |
| `NFP` | Employment Situation (payrolls, unemployment) | 08:30 | fred or rule |
| `ADP` | ADP private employment (Wednesday before NFP) | 08:15 | rule |
| `JOBLESS_CLAIMS` | weekly initial claims | 08:30 Thu (Wed on holidays) | rule |
| `GDP` | BEA GDP estimate (advance/second/third) | 08:30 | fred or rule |
| `PCE` | personal income & outlays (PCE prices) | 08:30 | fred or rule |
| `RETAIL_SALES` | Census advance retail sales (~mid-month) | 08:30 | fred or rule |
| `DURABLE_GOODS` | Census durable goods orders (~25th) | 08:30 | rule |
| `ECI` | Employment Cost Index (last business day of Jan/Apr/Jul/Oct) | 08:30 | rule |
| `JOLTS` | job openings | 10:00 | fred only |
| `ISM_MFG` / `ISM_SVC` | ISM PMIs (1st / 3rd business day) | 10:00 | rule |
| `UMICH_PRELIM` / `UMICH_FINAL` | U. Michigan sentiment + inflation expectations (2nd / last Friday) | 10:00 | rule |
| `CB_CONFIDENCE` | Conference Board consumer confidence (last Tuesday) | 10:00 | rule |

Central banks & fiscal:

| sym | what | time (ET) | date source |
| --- | --- | --- | --- |
| `FOMC` | rate decision (presser 14:30; SEP/dot plot flagged on quarterly meetings) | 14:00 | official (embedded Fed calendar 2024–2026) |
| `FOMC_MINUTES` | minutes, 3 weeks after the meeting | 14:00 | rule |
| `ECB` | ECB rate decision (presser 08:45) | 08:15 | official (embedded 2025–2026) |
| `BOJ` | Bank of Japan decision, overnight ET (time approximate) | ~23:00 | official (embedded 2025–2026) |
| `JACKSON_HOLE` | Fed Chair keynote at the KC Fed symposium (4th Friday of Aug) | 10:00 | rule |
| `QRA` | Treasury quarterly refunding statement | 08:30 | official (embedded 2025–2026) |
| `AUCTION_2Y…30Y` | Treasury coupon auctions (2/3/5/7/10/20/30-year) | 13:00 | official (TreasuryDirect API; appears once announced ~1–2 weeks ahead) |
| `US_ELECTION` | US presidential/midterm election day (even years) | 20:00 | official |

Index events & flows:

| sym | what | time (ET) | date source |
| --- | --- | --- | --- |
| `SPY_REBAL_ANNOUNCE` | S&P 500 quarterly rebalance press release (~1st Friday of Mar/Jun/Sep/Dec) | 17:15 | rule |
| `SPY_REBAL_EFFECTIVE` | S&P 500 rebalance trades at the close (3rd Friday, holiday-shifted) | 16:00 | official |
| `TRIPLE_WITCHING` | quarterly futures/options expiration | 16:00 | official |
| `OPEX` | monthly options expiration (3rd Friday of non-quad months) | 16:00 | official |
| `VIX_EXP` | VIX expiration/settlement (30 days before next monthly SPX expiry) | 09:30 | official |
| `QQQ_RECON_ANNOUNCE` | Nasdaq-100 reconstitution announcement (2nd Friday of Dec) | 20:00 | rule |
| `QQQ_RECON_EFFECTIVE` | Nasdaq-100 reconstitution trades at the close (3rd Friday of Dec) | 16:00 | official |
| `MSCI_REVIEW_ANNOUNCE` | MSCI index review results (~2nd Tuesday of Feb/May/Aug/Nov, ~23:00 CET) | 17:00 | rule |
| `MSCI_REVIEW_EFFECTIVE` | MSCI review trades at the close (last business day of review month) | 16:00 | official |
| `RUSSELL_PRELIM` | Russell recon preliminary add/delete lists (5 Fridays before June recon) | 18:00 | rule |
| `RUSSELL_RECON` | Russell reconstitution closing auction (4th Friday of June; 2nd Friday of Dec from 2026) | 16:00 | official |
| `QUARTER_END` | quarter-end close (rebalance flows) | 16:00 | official |

## Date sources & accuracy

- **official** — calendars published far in advance (FOMC) and index-methodology
  effective dates. Exact.
- **fred** — exact past *and future* BLS/BEA release dates from the FRED
  `release/dates` API. Enabled when a (free) key is present in `$FRED_API_KEY` or
  `config/fred_api_key.txt` — https://fred.stlouisfed.org/docs/api/api_key.html.
  Strongly recommended for exact CPI/PPI/NFP/GDP/PCE dates.
- **rule** — calendar approximations used without a key. NFP/claims/ISM rules are
  near-exact; CPI/PPI/GDP/PCE rules are right within a day or two in normal times
  (and wrong during anomalies like the late-2025 government shutdown delays).
  Announcement-date conventions (S&P/Nasdaq/MSCI) are approximate by nature.
  Filter `schedule_source` if you need confirmed dates only.

`summarize` (past events) pulls actuals from the keyless BLS API (CPI/PPI/NFP),
keyless FRED CSVs (fed funds target range, ECB deposit rate, claims, GDP, PCE,
retail sales, durable goods — current vintage), and TreasuryDirect auction
results (high yield, bid-to-cover); other events get descriptive text. Network
failures degrade to descriptive text, never errors.

## Maintenance

- Extend the embedded calendars in `scripts/market_moving_events/schedules.py` when next
  year's are published (a warning is printed for uncovered years):
  `FOMC_MEETINGS` (Fed), `ECB_DECISIONS`, `BOJ_DECISIONS_JST`, and `QRA_DATES`
  (each refunding statement names the next date; Nov 2026 not yet confirmed).
- Treasury auction events only appear once announced (~1–2 weeks ahead) or for
  the past ~2 years; the daily sliding-window run keeps them filled.
- HTTP responses are cached in `cache/` (flock-serialized, so the 18-process
  batch runner triggers one fetch, not eighteen). Safe to delete anytime.
