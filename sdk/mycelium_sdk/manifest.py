"""Module manifest: the contract between a module and the rest of the system.

The supervisor refuses to deploy anything whose manifest fails validate_manifest().
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
TOKEN_RE = re.compile(r"^[a-z0-9_*>-]+(\.[a-z0-9_*>-]+)*$")
RESERVED = {"sys", "brain", "build", "memory", "out", "trace", "sense", "rpc", "supervisor", "main"}


class ManifestError(ValueError):
    pass


class Permissions(BaseModel):
    network: bool = False  # may reach the internet (otherwise only the bus)
    actuation: bool = False  # may act on the real world (HA, money, messages); needs approval


class Resources(BaseModel):
    memory_mb: int = Field(default=256, ge=64, le=4096)
    cpus: float = Field(default=0.5, gt=0, le=4)


class Hooks(BaseModel):
    interval_seconds: list[int] = Field(default_factory=list)

    @field_validator("interval_seconds")
    @classmethod
    def _min_interval(cls, v: list[int]) -> list[int]:
        for s in v:
            if s < 10:
                raise ValueError("interval hooks must be >= 10 seconds")
        return v


class Manifest(BaseModel):
    name: str
    version: str = "0.1.0"
    purpose: str
    need: str = ""  # the observed need that caused this module to exist
    subscribes: list[str] = Field(default_factory=list)
    emits: list[str] = Field(default_factory=list)  # relative event names -> mod.<name>.<event>
    requests: list[str] = Field(default_factory=list)  # relative actions -> rpc.mod.<name>.<action>
    hooks: Hooks = Field(default_factory=Hooks)
    permissions: Permissions = Field(default_factory=Permissions)
    resources: Resources = Field(default_factory=Resources)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError("name must be lowercase slug, 2-31 chars, start with a letter")
        if v in RESERVED:
            raise ValueError(f"name '{v}' is reserved")
        return v

    @field_validator("purpose")
    @classmethod
    def _purpose(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("purpose must be a real sentence (>= 10 chars)")
        return v.strip()

    @field_validator("subscribes")
    @classmethod
    def _subs(cls, v: list[str]) -> list[str]:
        for s in v:
            if not TOKEN_RE.match(s):
                raise ValueError(f"invalid subject pattern: {s}")
            if s.startswith(("rpc.", "_INBOX")) or s in (">", "*"):
                raise ValueError(f"modules may not subscribe to {s}")
        return v

    @field_validator("emits", "requests")
    @classmethod
    def _relative(cls, v: list[str]) -> list[str]:
        for s in v:
            if "*" in s or ">" in s or not TOKEN_RE.match(s):
                raise ValueError(f"must be a concrete relative name, got: {s}")
        return v

    @model_validator(mode="after")
    def _no_self_loop(self) -> Manifest:
        own = f"mod.{self.name}."
        for s in self.subscribes:
            if s.startswith(own):
                raise ValueError(f"module subscribes to its own events ({s}); that is a loop")
        return self

    def event_subject(self, event: str) -> str:
        return f"mod.{self.name}.{event}"

    def rpc_subject(self, action: str) -> str:
        return f"rpc.mod.{self.name}.{action}"


def validate_manifest(data: dict[str, Any]) -> Manifest:
    try:
        return Manifest.model_validate(data)
    except ValidationError as e:
        raise ManifestError(str(e)) from e


def load_manifest(path: str | Path) -> Manifest:
    p = Path(path)
    if not p.exists():
        raise ManifestError(f"manifest not found: {p}")
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        raise ManifestError(f"invalid YAML in {p}: {e}") from e
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a mapping")
    return validate_manifest(data)
