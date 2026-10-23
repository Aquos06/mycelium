"""Reading the raw event log, the source of truth, one local day at a time.

Requests and traces are not memory material: a request is a question the system asked itself, a
trace is a decision about an event that is already in the log.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

NOT_MATERIAL = ("trace.", "rpc.", "_INBOX", "$")


class Event(BaseModel):
    """One row of the `events` table (or one line of a .jsonl fixture), validated on the way in."""

    model_config = ConfigDict(frozen=True)

    id: int
    ts: datetime
    subject: str
    source: str = ""
    is_request: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload", mode="before")
    @classmethod
    def _payload_from_json(cls, v: Any) -> Any:
        if v is None:
            return {}
        if isinstance(v, str):  # asyncpg hands jsonb back as text unless a codec is registered
            return json.loads(v)
        return v

    def localised(self, zone: ZoneInfo) -> Event:
        ts = self.ts if self.ts.tzinfo else self.ts.replace(tzinfo=zone)
        return self.model_copy(update={"ts": ts.astimezone(zone)})


def is_memory_material(subject: str, is_request: bool) -> bool:
    return not is_request and not subject.startswith(NOT_MATERIAL)


def day_bounds(day: date, tz: str) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(tz))
    return start, start + timedelta(days=1)


class EventSource(Protocol):
    async def for_day(self, day: date, tz: str) -> list[Event]: ...


class JsonlEvents:
    """Events from a .jsonl file (fixtures, replays). One object per line, shaped like an `events` row."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    async def for_day(self, day: date, tz: str) -> list[Event]:
        zone = ZoneInfo(tz)
        start, end = day_bounds(day, tz)
        out: list[Event] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = Event.model_validate_json(line).localised(zone)
            if is_memory_material(event.subject, event.is_request) and start <= event.ts < end:
                out.append(event)
        out.sort(key=lambda e: (e.ts, e.id))
        return out


class PostgresEvents:
    """Events from the tracer's table, through a read-only role. `source_filter` is a LIKE pattern for tests."""

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
