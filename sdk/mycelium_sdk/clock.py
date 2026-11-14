"""A time of day in the user's zone: the next one, and waiting for it.

    next_daily(now, time(21), zone)   the next 21:00 in `zone` strictly after `now`
    await sleep_until(due, now)       returns at `due` by the wall clock

Waiting is measured in UTC, so a day that changes to or from summer time is the hours it really has, and in short
steps against the wall clock, so a host that was asleep (a laptop running Docker overnight) is not hours late.
Used by a module's `@mod.at` and by memory's nightly consolidation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta, tzinfo

STEP_S = 60.0  # how often a wait looks at the wall clock again


def next_daily(now: datetime, at: time, zone: tzinfo | None = None) -> datetime:
    """The next `at` strictly after `now`, in `zone` (default: now's own)."""
    local = now.astimezone(zone) if zone is not None else now
    due = datetime.combine(local.date(), at, tzinfo=local.tzinfo)
    if due <= local:
        due = datetime.combine(local.date() + timedelta(days=1), at, tzinfo=local.tzinfo)
    return due


def seconds_until(due: datetime, now: datetime) -> float:
    """Real seconds: in UTC, since two times in one zone subtract as wall clocks and miss a summer-time change."""
    return (due.astimezone(UTC) - now.astimezone(UTC)).total_seconds()


async def sleep_until(
    due: datetime, now: Callable[[], datetime], stop: asyncio.Event | None = None, step: float | None = None
) -> bool:
    """Wait until `due` by the wall clock, looking at it every `step` seconds (STEP_S). False when `stop` was set
    first."""
    step = STEP_S if step is None else step
    while (left := seconds_until(due, now())) > 0:
        if stop is None:
            await asyncio.sleep(min(left, step))
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=min(left, step))
            return False
        except TimeoutError:
            pass
    return stop is None or not stop.is_set()
