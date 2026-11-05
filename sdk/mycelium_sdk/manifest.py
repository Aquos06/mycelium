"""Module manifest: the contract between a module and the rest of the system.

The supervisor refuses to deploy anything whose manifest fails validate_manifest().

`requests` is a list of names, or described (docs/ARCHITECTURE.md §4), so Main knows what to send:

    requests:
      add:
        description: Store one expense.
        params: {amount: number, description: string, day: optional date}
        returns: {id: number}

Either way `requests` is the names afterwards, and the descriptions are in `request_specs`: every reader of
the names keeps working, and the supervisor stores and serves the descriptions with the rest of the manifest.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .subjects import MODULE_LISTENS

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")  # \Z: `$` would also take a trailing newline
FIELD_RE = re.compile(r"^[a-z_][a-z0-9_]{0,40}\Z")  # a param or return field
TOKEN_RE = re.compile(r"^[a-z0-9_*>-]+(\.[a-z0-9_*>-]+)*\Z")
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


class RequestSpec(BaseModel):
    """One request a module answers, described: what it does, the fields it takes and what it gives back.
    Fields are `name: type` (number, string, date, bool, list, object...), `optional <type>` when it may be left
    out. YAML refuses `{day?: date}` in a flow mapping, so the word is the way; a block-style `day?:` is taken too."""

    description: str = Field(min_length=8, max_length=300)
    params: dict[str, str] = Field(default_factory=dict)
    returns: dict[str, str] = Field(default_factory=dict)

    @field_validator("params", "returns", mode="before")
    @classmethod
    def _fields(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        out: dict[str, str] = {}
        for name, kind in v.items():
            name, kind = str(name), "" if kind is None else str(kind).strip()
            if name.endswith("?"):  # `day?: date`, block style
                name = name[:-1]
                kind = kind if kind.startswith("optional") else f"optional {kind}".strip()
            if not FIELD_RE.match(name):
                raise ValueError(f"field {name!r}: a lowercase name (letters, digits, _)")
            if not 1 <= len(kind) <= 80:
                raise ValueError(f"field {name!r}: its type, in a few words")
            out[name] = kind
        return out

    def signature(self) -> str:
        """`{amount: number, day: optional date}`, as Main's prompt shows it."""
        return "{" + ", ".join(f"{k}: {t}" for k, t in self.params.items()) + "}"


class Manifest(BaseModel):
    name: str
    version: str = "0.1.0"
    purpose: str
    need: str = ""  # the observed need that caused this module to exist
    subscribes: list[str] = Field(default_factory=list)
    emits: list[str] = Field(default_factory=list)  # relative event names -> mod.<name>.<event>
    requests: list[str] = Field(default_factory=list)  # relative actions -> rpc.mod.<name>.<action>
    request_specs: dict[str, RequestSpec] = Field(default_factory=dict)  # what each takes; from described `requests`
    hooks: Hooks = Field(default_factory=Hooks)
    permissions: Permissions = Field(default_factory=Permissions)
    resources: Resources = Field(default_factory=Resources)

    @model_validator(mode="before")
    @classmethod
    def _described_requests(cls, data: Any) -> Any:
        """`requests: {add: {description, params, returns}}` -> the names in `requests`, the rest in `request_specs`.
        A description alone (`add: Store one expense.`) is a spec without fields."""
        if not isinstance(data, dict) or not isinstance(data.get("requests"), dict):
            return data
        described = data["requests"]
        specs = dict(data.get("request_specs") or {})
        for name, spec in described.items():
            if isinstance(spec, str):
                specs[name] = {"description": spec}
            elif spec is not None:
                specs[name] = spec
        return {**data, "requests": list(described), "request_specs": specs}

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
            if not s.startswith(tuple(p.removesuffix(">") for p in MODULE_LISTENS)):
                raise ValueError(f"modules may not subscribe to {s}; they listen to {', '.join(MODULE_LISTENS)}")
        return v

    @field_validator("emits", "requests")
    @classmethod
    def _relative(cls, v: list[str]) -> list[str]:
        for s in v:
            if "*" in s or ">" in s or not TOKEN_RE.match(s):
                raise ValueError(f"must be a concrete relative name, got: {s}")
        return v

    @model_validator(mode="after")
    def _specs_are_requests(self) -> Manifest:
        if unknown := sorted(set(self.request_specs) - set(self.requests)):
            raise ValueError(f"request_specs describe requests not in `requests`: {unknown}")
        return self

    def undescribed(self) -> list[str]:
        """Requests with no description: Main can call them only by guessing what they take."""
        return [r for r in self.requests if r not in self.request_specs]

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
