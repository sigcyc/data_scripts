"""Disk-cached HTTP fetches.

Safe under the parallel batch runner: a per-entry flock serializes the fetch so a
cold cache triggers one network call instead of one per process, and writes are
atomic (tmp + rename). On fetch failure a stale cache entry is served if present,
so offline runs degrade instead of failing.
"""
from __future__ import annotations

import fcntl
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import requests

CACHE_DIR = Path(__file__).resolve().parents[2] / "cache"
TIMEOUT = 30


@contextmanager
def _locked(name: str):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = CACHE_DIR / f"{name}.lock"
    with open(lock_path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cached_text(name: str, fetch: Callable[[], str], ttl_hours: float) -> str | None:
    """Return cached content for `name`, refreshing via `fetch()` when older than ttl."""
    path = CACHE_DIR / name
    with _locked(name):
        if path.exists() and time.time() - path.stat().st_mtime < ttl_hours * 3600:
            return path.read_text()
        try:
            text = fetch()
        except Exception as e:
            print(f"warning: fetch {name} failed ({e}); using stale cache" if path.exists()
                  else f"warning: fetch {name} failed ({e}); no cache", file=sys.stderr)
            return path.read_text() if path.exists() else None
        _atomic_write(path, text)
        return text


def get_text(name: str, url: str, ttl_hours: float = 12) -> str | None:
    def fetch() -> str:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text

    return cached_text(name, fetch, ttl_hours)


def post_json_text(name: str, url: str, payload: dict, ttl_hours: float = 12) -> str | None:
    def fetch() -> str:
        r = requests.post(url, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text

    return cached_text(name, fetch, ttl_hours)
