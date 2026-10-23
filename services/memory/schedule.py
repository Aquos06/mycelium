"""The nightly tick: at a local time each day, consolidate yesterday.

The time comes from MemorySettings.consolidate_at (MEMORY_CONSOLIDATE_AT=03:30; empty disables it,
`mctl consolidate` still works).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger("mycelium.memory.schedule")


def next_run(now: datetime, at: time, zone: ZoneInfo) -> datetime:
    """The next `at` in `zone` strictly after `now`."""
    local = now.astimezone(zone)
    due = datetime.combine(local.date(), at, tzinfo=zone)
    if due <= local:
        due = datetime.combine(local.date() + timedelta(days=1), at, tzinfo=zone)
    return due


async def nightly(
    run: Callable[[date], Awaitable[object]],
    at: time,
    tz: str,
    stop: asyncio.Event,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Call run(yesterday) at `at` local time every day until `stop` is set. A failed run is logged, not fatal."""
    zone = ZoneInfo(tz)
    while not stop.is_set():
        due = next_run(now(), at, zone)
        wait = max(0.0, (due - now().astimezone(zone)).total_seconds())
        log.info("next consolidation at %s (in %.0f min)", due.isoformat(timespec="minutes"), wait / 60)
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
            return
        except TimeoutError:
            pass
        day = due.date() - timedelta(days=1)
        try:
            await run(day)
        except Exception:
            log.exception("consolidation for %s failed", day)
