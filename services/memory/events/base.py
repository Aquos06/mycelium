"""What every event source offers, and the two rules every source applies."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from ..schemas import Event

NOT_MATERIAL = ("trace.", "rpc.", "_INBOX", "$")


def is_memory_material(subject: str, is_request: bool) -> bool:
    return not is_request and not subject.startswith(NOT_MATERIAL)


def day_bounds(day: date, tz: str) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(tz))
    return start, start + timedelta(days=1)


class EventSource(Protocol):
    async def for_day(self, day: date, tz: str) -> list[Event]: ...
