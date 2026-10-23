"""Events from the tracer's table. `source_filter` is a LIKE pattern for tests sharing a database."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from ..schemas import Event
from .base import day_bounds


class PostgresEvents:
    def __init__(self, pool, source_filter: str | None = None) -> None:
        self.pool = pool
        self.source_filter = source_filter

    async def for_day(self, day: date, tz: str) -> list[Event]:
        zone = ZoneInfo(tz)
        start, end = day_bounds(day, tz)
        rows = await self.pool.fetch(
            """SELECT id, ts, subject, source, is_request, payload FROM events
               WHERE ts >= $1 AND ts < $2 AND NOT is_request AND subject NOT LIKE 'trace.%'
                 AND ($3::text IS NULL OR source LIKE $3)
               ORDER BY ts, id""",
            start,
            end,
            self.source_filter,
        )
        return [Event.model_validate(dict(r)).localised(zone) for r in rows]
