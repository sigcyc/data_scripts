"""Compare locally-saved IC500 (from akshare/sina) against cyc.Df.load_data('a_futures').

Joins on date, reports row counts, disagreements on close price, and gaps.
"""

from pathlib import Path

import cyc
import pandas as pd
import polars as pl

DATA_FILE = Path(__file__).parent / "data" / "ic500_daily.parquet"


def load_local() -> pl.DataFrame:
    return pl.read_parquet(DATA_FILE).select("date", "close").rename({"close": "close_akshare"})


def load_cyc() -> pl.DataFrame:
    df = cyc.Df.load_data("a_futures").df
    return (
        df.filter(pl.col("sym") == "IC500")
        .select("date", "close")
        .rename({"close": "close_cyc"})
    )


def main() -> None:
    local = load_local()
    ref = load_cyc()

    joined = local.join(ref, on="date", how="full", coalesce=True).sort("date")
    overlap = joined.filter(pl.col("close_akshare").is_not_null() & pl.col("close_cyc").is_not_null())
    local_only = joined.filter(pl.col("close_cyc").is_null())
    cyc_only = joined.filter(pl.col("close_akshare").is_null())

    diff = overlap.with_columns(
        (pl.col("close_akshare") - pl.col("close_cyc")).abs().alias("abs_diff"),
        ((pl.col("close_akshare") - pl.col("close_cyc")) / pl.col("close_cyc") * 100).abs().alias("pct_diff"),
    )
    mismatches = diff.filter(pl.col("abs_diff") > 0.01).sort("abs_diff", descending=True)

    pd.set_option("display.max_rows", 30)

    print("=" * 60)
    print(f"akshare rows:  {local.height:>6}   range {local['date'].min()} → {local['date'].max()}")
    print(f"cyc rows:      {ref.height:>6}   range {ref['date'].min()} → {ref['date'].max()}")
    print(f"overlap rows:  {overlap.height:>6}")
    print(f"akshare-only:  {local_only.height:>6}")
    print(f"cyc-only:      {cyc_only.height:>6}")
    print("=" * 60)

    if overlap.height:
        s = diff.select(
            pl.col("abs_diff").max().alias("max_abs"),
            pl.col("abs_diff").mean().alias("mean_abs"),
            pl.col("pct_diff").max().alias("max_pct"),
            pl.col("pct_diff").mean().alias("mean_pct"),
        )
        print("close-price diff stats:")
        print(s)
        print(f"\nmismatches (|diff| > 0.01): {mismatches.height}")
        if mismatches.height:
            print(mismatches.head(20))

    if local_only.height:
        print(f"\ndates in akshare only (first 20):")
        print(local_only.head(20))
    if cyc_only.height:
        print(f"\ndates in cyc only (first 20):")
        print(cyc_only.head(20))
    globals().update(locals())



if __name__ == "__main__":
    main()
