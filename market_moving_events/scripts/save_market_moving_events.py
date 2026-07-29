import typer
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cyc import get_data_path
from market_moving_events import build_events_df

DF_TYPE = Path(__file__).stem.removeprefix("save_")


def main(
    date: str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d"),
    write: bool = False,
    data_dir: str | None = None,
):
    df = build_events_df(date)

    if write:
        base = Path(data_dir).expanduser() if data_dir else get_data_path(DF_TYPE)
        path = base / f"{date}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
    else:
        print(df)
        globals().update(locals())


if __name__ == "__main__":
    typer.run(main)
