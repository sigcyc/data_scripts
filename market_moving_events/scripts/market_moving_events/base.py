"""Shared primitives: event record, eastern-time helpers, NYSE-session calendar math."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

ET = ZoneInfo("America/New_York")


@dataclass
class Event:
    dt: datetime  # tz-aware, America/New_York
    sym: str
    name: str
    release_for: str | None = None  # reference period, e.g. "May 2026" or "Q1 2026"
    schedule_source: str = "rule"  # "official" | "fred" | "rule"
    summary_fallback: str | None = None  # summary text when no data-driven summary exists
    ref: dict = field(default_factory=dict)  # extra context for the summarizer


def at_et(d: Date, hour: int, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=ET)


@lru_cache(maxsize=1)
def _xnys():
    # extend the calendar window: the script is meant to run for future dates
    today = datetime.now(ET).date()
    return xcals.get_calendar("XNYS", start="2015-01-01", end=str(today + timedelta(days=365 * 3)))


def is_session(d: Date) -> bool:
    return _xnys().is_session(d)


def prev_session(d: Date) -> Date:
    """Latest NYSE session on or before d."""
    while not is_session(d):
        d -= timedelta(days=1)
    return d


def next_session(d: Date) -> Date:
    """Earliest NYSE session on or after d."""
    while not is_session(d):
        d += timedelta(days=1)
    return d


def nth_weekday(year: int, month: int, weekday: int, n: int) -> Date:
    """n-th (1-based) weekday (Mon=0) of a month."""
    first = Date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> Date:
    nxt = Date(year + 1, 1, 1) if month == 12 else Date(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def nth_bday(year: int, month: int, n: int) -> Date:
    """n-th (1-based) NYSE session of a month."""
    d = next_session(Date(year, month, 1))
    for _ in range(n - 1):
        d = next_session(d + timedelta(days=1))
    return d


def last_bday(year: int, month: int) -> Date:
    nxt = Date(year + 1, 1, 1) if month == 12 else Date(year, month + 1, 1)
    return prev_session(nxt - timedelta(days=1))


def prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def month_name(year: int, month: int) -> str:
    return Date(year, month, 1).strftime("%B %Y")
