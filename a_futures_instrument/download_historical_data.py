#!/usr/bin/env python3
"""Download CFFEX historical futures data zips for a month range.

Source page: http://www.cffex.com.cn/cn/lssjxz.html
URL pattern: http://www.cffex.com.cn/sj/historysj/{YYYYMM}/zip/{YYYYMM}.zip

Each zip contains daily CSV files for that month. Earliest available month is
2010-04. Months without data (future months, non-trading months) are served as
302 redirects to an error page; the script detects and skips those.
"""
import argparse
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "http://www.cffex.com.cn/sj/historysj/{ym}/zip/{ym}.zip"
MIN_MONTH = (2010, 4)
USER_AGENT = "Mozilla/5.0 (compatible; cffex-historical-downloader)"


def parse_month(s: str) -> tuple[int, int]:
    parts = s.split("-")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {s!r}")
    year, month = int(parts[0]), int(parts[1])
    if not (1 <= month <= 12):
        raise argparse.ArgumentTypeError(f"month out of range in {s!r}")
    return year, month


def iter_months(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m == 13:
            m = 1
            y += 1


def download_month(year: int, month: int, out_dir: Path) -> str:
    ym = f"{year:04d}{month:02d}"
    dest = out_dir / f"{ym}.zip"
    if dest.exists() and dest.stat().st_size > 0:
        return "skip (exists)"

    req = Request(BASE_URL.format(ym=ym), headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=60) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "zip" not in ctype.lower():
                return f"missing (content-type={ctype!r})"
            data = resp.read()
    except HTTPError as e:
        return f"http error {e.code}"
    except URLError as e:
        return f"url error: {e.reason}"

    tmp = dest.with_suffix(".zip.part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return f"downloaded ({len(data):,} bytes)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=parse_month, required=True, help="first month, YYYY-MM")
    ap.add_argument("--end", type=parse_month, required=True, help="last month, YYYY-MM (inclusive)")
    ap.add_argument("--out", type=Path, default=Path("data"), help="output directory (default: ./data)")
    args = ap.parse_args()

    if args.start < MIN_MONTH:
        print(f"error: earliest available month is {MIN_MONTH[0]}-{MIN_MONTH[1]:02d}", file=sys.stderr)
        return 2
    if args.end < args.start:
        print(f"error: --end precedes --start", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)

    for year, month in iter_months(args.start, args.end):
        status = download_month(year, month, args.out)
        print(f"{year:04d}-{month:02d}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
