"""Events from a .jsonl file: one object per line, shaped like an `events` row (fixtures, replays)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from ..schemas import Event
from .base import day_bounds, is_memory_material


class JsonlEvents:
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
