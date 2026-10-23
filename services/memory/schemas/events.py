"""One row of the `events` table (or one line of a .jsonl fixture), validated on the way in."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Event(BaseModel):
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
