"""Memory's environment, as one validated model (see mycelium_sdk.settings)."""

from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Any

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

    @field_validator("tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        return timezone(v)

    @field_validator("consolidate_at", mode="before")
    @classmethod
    def _empty_means_off(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v
