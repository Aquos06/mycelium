"""Reading the raw event log, the source of truth, one local day at a time.

Requests and traces are not memory material: a request is a question the system asked itself, a
trace is a decision about an event that is already in the log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

NOT_MATERIAL = ("trace.", "rpc.", "_INBOX", "$")


@dataclass
class Event:
    id: int
    ts: datetime
    subject: str
    source: str
    payload: dict[str, Any]


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
            row = json.loads(line)
            if not is_memory_material(row["subject"], bool(row.get("is_request"))):
                continue
            ts = datetime.fromisoformat(row["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=zone)
            if not (start <= ts < end):
                continue
            out.append(
                Event(
                    int(row["id"]), ts.astimezone(zone), row["subject"], row.get("source", ""), row.get("payload") or {}
                )
            )
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
            """SELECT id, ts, subject, source, payload FROM events
               WHERE ts >= $1 AND ts < $2 AND NOT is_request AND subject NOT LIKE 'trace.%'
                 AND ($3::text IS NULL OR source LIKE $3)
               ORDER BY ts, id""",
            start,
            end,
            self.source_filter,
        )
        out = []
        for r in rows:
            payload = r["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            out.append(Event(r["id"], r["ts"].astimezone(zone), r["subject"], r["source"], payload or {}))
        return out
