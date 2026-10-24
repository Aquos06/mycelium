"""Events from the tracer's table (mycelium_sdk.db.core.events), through the async engine.
`source_filter` is a LIKE pattern for tests sharing a database."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from mycelium_sdk.db.core import events

from ..schemas import Event
from .base import day_bounds


class PostgresEvents:
    def __init__(self, engine: AsyncEngine, source_filter: str | None = None) -> None:
        self.engine = engine
        self.source_filter = source_filter

    async def for_day(self, day: date, tz: str) -> list[Event]:
        zone = ZoneInfo(tz)
        start, end = day_bounds(day, tz)
        stmt = (
            select(events.c.id, events.c.ts, events.c.subject, events.c.source, events.c.is_request, events.c.payload)
            .where(events.c.ts >= start, events.c.ts < end, events.c.is_request.is_(False))
            .where(~events.c.subject.like("trace.%"))
        )
        if self.source_filter:
            stmt = stmt.where(events.c.source.like(self.source_filter))
        stmt = stmt.order_by(events.c.ts, events.c.id)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [Event.model_validate(dict(r)).localised(zone) for r in rows]
