"""Service settings: the environment, read once at start, validated, documented by the fields.

    class MemorySettings(ServiceSettings):
        tz: str = Field(default="Asia/Taipei", validation_alias="MEMORY_TZ")

    settings = MemorySettings()              # from the environment (compose, .env)
    MemorySettings.model_validate({...})     # from a dict and nothing else: tests

Every field names its env var in `validation_alias`, so a wrong value fails at start with the
variable's name in the error instead of a KeyError at 3 a.m. `nats_url` and `log_level` are common
to every service.
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVELS = tuple(logging.getLevelNamesMapping())


def timezone(value: str) -> str:
    """A valid IANA zone name, or a clear error."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown timezone {value!r}") from e
    return value


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    nats_url: str = Field(default="nats://nats:4222", validation_alias="NATS_URL")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator("log_level")
    @classmethod
    def _level(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in LOG_LEVELS:
            raise ValueError(f"must be one of {', '.join(LOG_LEVELS)}")
        return v
