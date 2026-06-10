# form13f

Quarterly institutional holdings datasets built from the
[SEC Form 13F structured data sets](https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets).

For each quarter-end report period the script downloads the SEC zip covering
that period's filing window, merges the member files, de-duplicates
amendments, resolves CUSIPs to ticker symbols, and writes one parquet:

```
data/20250331.parquet     # holdings as of 2025-03-31
```

## Usage

```bash
pip install -r requirements.txt

python save_form13f.py 2025                 # all four quarters of 2025
python save_form13f.py 2025q1               # one quarter
python save_form13f.py 20250331 20250630    # explicit period end dates
python save_form13f.py 2024 2025 --force    # rebuild even if files exist
```

Runs are incremental: periods whose parquet already exists are skipped.
Earliest available period is `20130331` (the SEC data sets begin with filings
received in 2013 Q2). The first couple of 2013 periods are sparse — XML 13F
filing was phased in during 2013, and the data sets only cover XML filings
(period 20130331 has just ~70 managers; coverage is full from 20130630 on).

Environment (both optional, read from the env or a gitignored `.env` file
next to the script):

- `OPENFIGI_API_KEY` — free key from <https://www.openfigi.com/api>. Without
  it, mapping is throttled to ~250 CUSIPs/min (a fresh quarter has ~38k unique
  CUSIPs, so the **first** build takes a few hours; with a key ~2 min).
  Mappings persist in `cache/cusip_ticker.parquet`, so subsequent quarters
  only map the few thousand CUSIPs not seen before.
- `SEC_USER_AGENT` — identification sent to sec.gov per their fair-access
  policy (defaults to an address-bearing string).

Flags: `--force` (rebuild), `--skip-tickers` (null ticker column, no API
calls), `--map-limit N` (map at most N new CUSIPs, for testing), `--data-dir`.

## Output schema

One row per holding line (a manager can legitimately report the same CUSIP on
several rows: different discretion, put/call, or sub-manager splits).

| column | type | notes |
|---|---|---|
| period_of_report | date | quarter end, same for all rows in a file |
| cik | str | filing manager CIK, zero-padded as in EDGAR |
| manager_name | str | COVERPAGE.FILINGMANAGER_NAME |
| filing_date | date | |
| submission_type | str | `13F-HR` or `13F-HR/A` |
| report_type | str | e.g. `13F HOLDINGS REPORT`, `13F COMBINATION REPORT` |
| is_amendment / amendment_no / amendment_type | bool/int/str | |
| accession_number | str | EDGAR accession |
| issuer_name / title_of_class | str | as reported |
| cusip | str | 9 chars, uppercased |
| figi | str | as reported (SEC added this column mid-2023; null before) |
| deliverable_symbol | str | raw OpenFIGI ticker of the security itself: plain symbol for equities, full bond descriptor for debt (e.g. `BABA 0.5 06/01/31`); null if unmapped |
| underlying_symbol | str | equity ticker of the underlier: = deliverable_symbol for equities; issuer symbol parsed from the FIGI bond ticker for Corp/Pfd (`BABA 0.5 06/01/31` → `BABA`); null for Govt/Muni/Mtge/unmapped |
| value | int | position value in USD. **Reported in 1000s of USD before the 2023-01 rule change** (i.e. periods up to 20220930, and a mix of conventions for 20221231) |
| shares | int | SSHPRNAMT |
| shares_type | str | `SH` shares / `PRN` principal amount |
| put_call | str | `Put`, `Call`, or null (CUSIP is the underlying) |
| investment_discretion | str | `SOLE`/`DFND`/`OTR` |
| other_manager | str | sequence number(s) into OTHERMANAGER2.tsv, kept raw |
| other_manager_names | str | resolved names from OTHERMANAGER2.tsv, `; `-joined when several |
| other_manager_ciks | str | CIKs of those managers from OTHERMANAGER2.tsv, same order |
| voting_sole / voting_shared / voting_none | int | |

## Design notes

**Which zip covers a period.** The SEC packages filings by *receipt window*,
not report period. Through 2023 the windows are calendar quarters
(`2023q3_form13f.zip` = filings received Jul–Sep 2023, mostly for the
2023-06-30 period). From 2024 the windows shifted to match the 13F due date
cycle (`01mar2025-31may2025_form13f.zip` covers the 2025-03-31 period, due
2025-05-15). The script maps period → zip accordingly and then filters
`SUBMISSION.PERIODOFREPORT == period`, which in a sampled window keeps ~92%
of submissions (the rest are late filings/amendments for older periods).
Consequence: filings for period P submitted *after* P's window closed (rare)
are not picked up.

**Merge.** `INFOTABLE` (holdings) ⟕ `SUBMISSION` (CIK, dates, type) ⟕
`COVERPAGE` (manager name, amendment info), joined on `ACCESSION_NUMBER`.
`OTHERMANAGER2.tsv` (the "other managers" lookup) is joined in as
`other_manager_names`; `other_manager` keeps the raw sequence numbers.
13F-NT notice filings
carry no holdings and are dropped.

**Amendment handling.** Within a period and manager, the last
original-or-RESTATEMENT filing wins (an amendment with unspecified type is
treated as a restatement), and later NEW HOLDINGS amendments are added on
top. This prevents double counting when a manager amends.

**Tickers.** OpenFIGI v3 mapping, two passes: (1) US composite listing
(`exchCode: "US"`), (2) for misses, any listing but only `marketSector ==
"Equity"` — so corporate-bond CUSIPs stay null instead of getting tickers
like `AAPL 2.4 05/03/23`. Letter-prefixed identifiers (foreign issuers, e.g.
Allegion `G0176J109`) are sent as `ID_CINS`. CUSIPs are mapped in descending
order of total reported value and the cache is flushed periodically, so an
interrupted run keeps the most important names. Tickers reflect symbology at
mapping time, not as of the report period (delisted/renamed securities may
stay null or differ from their historical symbol).

**Caches.** Downloaded zips are kept in `cache/raw/` (~90 MB/quarter, safe to
delete; they re-download on demand). CUSIP→ticker mappings accumulate in
`cache/cusip_ticker.parquet` with name/security-type/exchange metadata —
delete it to force a full remap.
