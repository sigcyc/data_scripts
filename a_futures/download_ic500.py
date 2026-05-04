"""Download IC500 / IC1000 / IF300 index daily data via akshare.

  IC500  = CSI 500   (中证500)  sh000905
  IM1000 = CSI 1000  (中证1000) sh000852
  IF300  = CSI 300   (沪深300)  sh000300
"""

from datetime import date
from pathlib import Path

import akshare as ak
import pandas as pd

OUTPUT_FILE = Path("/Volumes/ssd/a_futures/part0.parquet")

SYMBOLS = {
    "IC500": "sh000905",
    "IM1000": "sh000852",
    "IF300": "sh000300",
}
YEARS_BACK = 10


def download_one(sym: str, ak_symbol: str, start: date, end: date) -> pd.DataFrame:
    raw = ak.stock_zh_index_daily(symbol=ak_symbol)
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    df = raw[(raw["date"] >= start) & (raw["date"] <= end)].copy()
    df["sym"] = sym
    return df[["date", "sym", "open", "high", "low", "close", "volume"]]


def main() -> None:
    today = date.today()
    start = today.replace(year=today.year - YEARS_BACK)
    parts = [download_one(sym, ak_sym, start, today) for sym, ak_sym in SYMBOLS.items()]
    df = pd.concat(parts, ignore_index=True).sort_values(["sym", "date"]).reset_index(drop=True)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_FILE, index=False)

    print(f"Saved {len(df)} rows to {OUTPUT_FILE}")
    print(df.groupby("sym")["date"].agg(["min", "max", "count"]))

    globals().update(locals())


if __name__ == "__main__":
    main()
