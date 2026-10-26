"""Memory's environment, as one validated model (see mycelium_sdk.settings)."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field, field_validator

from mycelium_sdk import ServiceSettings, timezone


class MemorySettings(ServiceSettings):
    database_url: str = Field(
        validation_alias=AliasChoices("MEMORY_DATABASE_URL", "DATABASE_URL"),
        description="memory's own database when it has one (ARCHITECTURE §12), else the shared one",
    )
    schema_name: str = Field(default="memory", validation_alias="MEMORY_SCHEMA", pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    vault_dir: Path = Field(default=Path("/vault"), validation_alias="MEMORY_VAULT_DIR")
    tz: str = Field(default="Asia/Taipei", validation_alias="MEMORY_TZ", description="local day boundaries")
    consolidate_at: time | None = Field(
        default=time(3, 30),
        validation_alias="MEMORY_CONSOLIDATE_AT",
        description="local time of the nightly consolidation; empty disables it (mctl consolidate still works)",
    )

    embed: bool = Field(
        default=True,
        validation_alias="MEMORY_EMBED",
        description="embed notes and summaries through the gateway's embed slot; off, recall has no fuzzy rung",
    )
    embed_every: int = Field(
        default=10,
        ge=0,
        validation_alias="MEMORY_EMBED_EVERY",
        description="minutes between sweeps for rows without a vector; 0 sweeps only at start, after consolidation and on mctl embed",
    )
    embed_batch: int = Field(default=64, ge=1, le=256, validation_alias="MEMORY_EMBED_BATCH")
    embed_timeout: float = Field(
        default=60.0, gt=0, validation_alias="MEMORY_EMBED_TIMEOUT", description="seconds per batch"
    )
    embed_min_score: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        validation_alias="MEMORY_EMBED_MIN_SCORE",
        description="cosine similarity under which a neighbour is noise and recall leaves it out",
    )

    decide: bool = Field(
        default=True,
        validation_alias="MEMORY_DECIDE",
        description="the decide step for vague questions, through the gateway's decide slot; off, embeddings alone",
    )
    decide_floor: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        validation_alias="MEMORY_DECIDE_FLOOR",
        description="score under which a candidate is not about the question; empty: the scorer's own floor (providers.yaml)",
    )
    decide_rounds: int = Field(
        default=2,
        ge=1,
        le=5,
        validation_alias="MEMORY_DECIDE_ROUNDS",
        description="score, hop, score again: how many times",
    )
    decide_timeout: float = Field(
        default=30.0, gt=0, validation_alias="MEMORY_DECIDE_TIMEOUT", description="seconds per scoring call"
    )
    decide_candidates: int = Field(
        default=200,
        ge=1,
        validation_alias="MEMORY_DECIDE_CANDIDATES",
        description="catalogue rows per round; above it the embedding neighbours are scored instead",
    )
    decide_days: int = Field(
        default=14,
        ge=0,
        validation_alias="MEMORY_DECIDE_DAYS",
        description="day summaries this recent are in the catalogue",
    )

    @field_validator("tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        return timezone(v)

    @field_validator("consolidate_at", "decide_floor", mode="before")
    @classmethod
    def _empty_means_off(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v

    def today(self) -> date:
        """The local date: what "yesterday" and a fact without a day mean. The container's clock is UTC."""
        return datetime.now(ZoneInfo(self.tz)).date()
