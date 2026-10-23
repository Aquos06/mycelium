"""Main's environment, as one validated model (see mycelium_sdk.settings)."""

from __future__ import annotations

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

    @field_validator("tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        return timezone(v)
