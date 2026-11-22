"""Main's environment, as one validated model (see mycelium_sdk.settings)."""

from __future__ import annotations

from datetime import time

from pydantic import Field, field_validator

from mycelium_sdk import ServiceSettings, timezone


class MainSettings(ServiceSettings):
    tz: str = Field(default="Asia/Taipei", validation_alias="MAIN_TZ", description="what 'today' means in the prompt")
    max_turns: int = Field(default=20, ge=1, validation_alias="MAIN_MAX_TURNS", description="thread turns kept in KV")
    llm_timeout: float = Field(
        default=90.0,
        gt=0,
        validation_alias="MAIN_LLM_TIMEOUT",
        description="seconds per planner round; raise it for a cold local model",
    )
    currency: str = Field(
        default="TWD",
        pattern=r"^[A-Za-z]{3}$",
        validation_alias="MAIN_CURRENCY",
        description="money in what Main shows (a table's amounts): an ISO code, TWD, USD, EUR",
    )

    wake_every: int = Field(
        default=15,
        ge=1,
        validation_alias="MAIN_WAKE_EVERY",
        description="minutes between Main's own looks: modules down, cards left waiting, and what was held (quiet "
        "hours, a chat in progress, the budget) tried again",
    )
    quiet_hours: str = Field(
        default="23:00-08:00",
        validation_alias="MAIN_QUIET_HOURS",
        description="HH:MM-HH:MM in MAIN_TZ when only an alert is told; empty: none",
    )
    wake_budget: int = Field(
        default=3,
        ge=0,
        validation_alias="MAIN_WAKE_BUDGET",
        description="messages a day Main sends without being asked; an alert is told even when they are spent",
    )
    wake_channels: str = Field(
        default="telegram,web",
        validation_alias="MAIN_WAKE_CHANNELS",
        description="channels Main may write to first: the one Hansen last wrote in, of these",
    )
    checkins: str = Field(
        default="08:30,21:00",
        validation_alias="MAIN_CHECKINS",
        description="HH:MM times in MAIN_TZ when Main looks at the day and writes Hansen a message, or stays quiet; "
        "each counts against MAIN_WAKE_BUDGET; empty: none",
    )

    @field_validator("tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        return timezone(v)

    @field_validator("checkins")
    @classmethod
    def _checkins(cls, v: str) -> str:
        checkin_times(v)
        return v

    @field_validator("quiet_hours")
    @classmethod
    def _quiet(cls, v: str) -> str:
        quiet_hours(v)
        return v.strip()


def checkin_times(v: str) -> tuple[time, ...]:
    """Check-in times: 08:30,21:00 -> (08:30, 21:00), sorted and once each; empty -> ()."""
    try:
        times = {time.fromisoformat(p.strip()) for p in v.split(",") if p.strip()}
    except ValueError as e:
        raise ValueError(f"check-ins {v!r}: HH:MM times separated by commas, like 08:30,21:00") from e
    if any(t.tzinfo for t in times):
        raise ValueError(f"check-ins {v!r}: times in MAIN_TZ, without a zone of their own")
    return tuple(sorted(times))


def quiet_hours(v: str) -> tuple[time, time] | None:
    """Quiet hours as two times: 23:00-08:00 -> (23:00, 08:00); empty -> None."""
    if not v.strip():
        return None
    try:
        start, end = (time.fromisoformat(p.strip()) for p in v.split("-"))
    except ValueError as e:
        raise ValueError(f"quiet hours {v!r}: HH:MM-HH:MM, like 23:00-08:00") from e
    if start.tzinfo or end.tzinfo:
        raise ValueError(f"quiet hours {v!r}: times in MAIN_TZ, without a zone of their own")
    if start == end:
        raise ValueError(f"quiet hours {v!r}: the start and the end are the same")
    return start, end
