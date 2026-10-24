"""Periods: a day's week and month, the key each is known by, the file each lives in, the days each covers.

    week   2026-W43   summaries/2026/W43.md   ISO week, Monday to Sunday
    month  2026-10    summaries/2026/10.md

Pure functions on dates and strings; everything that names a period goes through here.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

Period = Literal["week", "month"]

PERIOD_KEY_RE: dict[str, re.Pattern[str]] = {
    "week": re.compile(r"^(\d{4})-W(\d{2})$"),
    "month": re.compile(r"^(\d{4})-(\d{2})$"),
}


def week_key(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def month_key(day: date) -> str:
    return f"{day:%Y-%m}"


def parse_period_key(period: str, key: str) -> str:
    """The key normalised ('2026-w42' -> '2026-W42') or a ValueError that names the problem."""
    if period not in PERIOD_KEY_RE:
        raise ValueError(f"unknown period {period!r}; use week or month")
    key = key.strip().upper()
    m = PERIOD_KEY_RE[period].match(key)
    example = "2026-W43" if period == "week" else "2026-10"
    if not m:
        raise ValueError(f"key {key!r} is not a {period} key like {example}")
    try:
        if period == "week":
            date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        else:
            date(int(m.group(1)), int(m.group(2)), 1)
    except ValueError as e:
        raise ValueError(f"key {key!r}: {e}") from e
    return key


def period_path(period: str, key: str) -> str:
    key = parse_period_key(period, key)
    year, rest = key.split("-", 1)
    return f"summaries/{year}/{rest}.md"


def period_days(period: str, key: str) -> list[date]:
    """Every day of the period, in order."""
    key = parse_period_key(period, key)
    year, rest = key.split("-", 1)
    if period == "week":
        return [date.fromisocalendar(int(year), int(rest[1:]), n) for n in range(1, 8)]
    first = date(int(year), int(rest), 1)
    following = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return [first + timedelta(days=i) for i in range((following - first).days)]


def periods_closed_by(day: date) -> list[tuple[str, str]]:
    """A Sunday closes its ISO week; the last day of a month closes the month."""
    closed: list[tuple[str, str]] = []
    if day.weekday() == 6:
        closed.append(("week", week_key(day)))
    if (day + timedelta(days=1)).day == 1:
        closed.append(("month", month_key(day)))
    return closed
