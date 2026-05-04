import polars as pl
from cyc.ds import Ds


TEXT_COLUMNS = {
    "Report_Date_as_YYYY-MM-DD",
    "Market_and_Exchange_Names",
    "CFTC_Contract_Market_Code",
    "CFTC_Market_Code",
    "CFTC_Commodity_Code",
    "Contract_Units",
    "CFTC_Contract_Market_Code_Quotes",
    "CFTC_Market_Code_Quotes",
    "CFTC_Commodity_Code_Quotes",
    "CFTC_SubGroup_Code",
    "FutOnly_or_Combined",
}
FLOAT_COLUMN_KEYWORDS = ("Pct", "Conc_")


def parse_numeric_column(column_name: str, dtype: pl.DataType) -> pl.Expr:
    """Cast numeric-looking string columns into the requested dtype."""
    return (
        pl.when(
            pl.col(column_name).is_null()
            | (pl.col(column_name).str.strip_chars() == "")
        )
        .then(None)
        .otherwise(pl.col(column_name).str.strip_chars())
        .cast(dtype, strict=False)
        .alias(column_name)
    )


df = pl.read_csv("e-mini-sp500-futures.txt")

string_numeric_columns = [
    column_name
    for column_name, dtype in df.schema.items()
    if dtype == pl.String and column_name not in TEXT_COLUMNS
]

float_columns = [
    column_name
    for column_name in string_numeric_columns
    if any(keyword in column_name for keyword in FLOAT_COLUMN_KEYWORDS)
]
int_columns = [column_name for column_name in string_numeric_columns if column_name not in float_columns]

if float_columns:
    df = df.with_columns(
        [parse_numeric_column(column_name, pl.Float64) for column_name in float_columns]
    )
if int_columns:
    df = df.with_columns(
        [parse_numeric_column(column_name, pl.Int64) for column_name in int_columns]
    )


df = df.with_columns(
    pl.col("Report_Date_as_YYYY-MM-DD").str.to_date().alias("date"),
)

df = df.with_columns([pl.col('date').cast(pl.Datetime('ns')).alias('time'), pl.col('Market_and_Exchange_Names').alias('sym')])


df.write_parquet('futures_report.parquet')
