"""Scheduled market-moving events (CPI, PPI, jobs, FOMC, index rebalances, ...).

build_events_df(date) returns one row per event on that date:
  time            tz-aware event time (America/New_York)
  sym             event code, e.g. CPI / NFP / FOMC / SPY_REBAL_EFFECTIVE
  event_name      human-readable description
  release_for     reference period of the release, when applicable
  event_date_type "actual" if the event time has passed at build time, else "expected"
  summarize       what happened (filled for past events only)
  schedule_source "official" | "fred" | "rule" — how the date was determined
"""
from __future__ import annotations

from datetime import date as Date, datetime

import polars as pl

from .base import ET
from . import schedules, summaries

SCHEMA = {
    "time": pl.Datetime("ns", "America/New_York"),
    "sym": pl.String,
    "event_name": pl.String,
    "release_for": pl.String,
    "event_date_type": pl.String,
    "summarize": pl.String,
    "schedule_source": pl.String,
}


def build_events_df(date: str) -> pl.DataFrame:
    """All scheduled market-moving events for one date ("YYYYMMDD")."""
    d = Date(int(date[:4]), int(date[4:6]), int(date[6:8]))
    now = datetime.now(ET)
    rows = []
    for ev in sorted(schedules.events_for(d), key=lambda e: (e.dt, e.sym)):
        happened = ev.dt <= now
        rows.append({
            "time": ev.dt,
            "sym": ev.sym,
            "event_name": ev.name,
            "release_for": ev.release_for,
            "event_date_type": "actual" if happened else "expected",
            "summarize": summaries.summarize(ev) if happened else None,
            "schedule_source": ev.schedule_source,
        })
    return pl.DataFrame(rows, schema=SCHEMA)
