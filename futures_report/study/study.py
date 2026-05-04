import polars as pl
from cyc import *


df = Df.load_data_single("futures_report")

df.add_stock('close')



ds.group_by(ds.time.dt.truncate("1mo")).agg(pl.col("Dealer_Positions_Short_All").mean())
ds.group_by(pl.col("time").dt.truncate("1mo")).agg(
    pl.col("Dealer_Positions_Short_All").mean()
)

ds.group_by([pl.col("sym"), pl.col("time").dt.truncate("1mo")]).agg(
    pl.col("Dealer_Positions_Short_All").mean()
).sort([pl.col("sym"), pl.col("time")])._A
