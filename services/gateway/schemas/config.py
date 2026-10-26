"""providers.yaml -> GatewayConfig: which provider serves each slot.

    budget_usd_month: 30
    planner:                       # a slot: one job the system needs a model for
      active: claude               # the provider that answers
      shadow: ollama               # optional: gets every request too, only logs
      claude: {kind: claude, model: claude-sonnet-5-5, price_in_per_m: 3.0, price_out_per_m: 15.0}
      ollama: {kind: ollama, model: qwen2.5:14b}

Every top-level key except `budget_usd_month` is a slot. Inside a slot, every key except `active`
and `shadow` is a provider. A provider's `kind` (kinds.py) brings its default endpoint and key env
var, so an entry is usually just `kind` and `model`; `endpoint` and `key_env` override. `kind` may
be omitted: an `endpoint` means a generic openai-compatible server, otherwise claude. Keys are never
in this file, only the name of the env var that holds one.

These same models are what a settings page will edit later (rpc.llm.config.*); the yaml is the seed.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .kinds import KINDS, KindInfo, Protocol, ProviderKind

KeyState = Literal["ok", "missing", "not-needed"]


class ProviderConfig(BaseModel):
    """One model behind one name: which vendor, how to reach it, what it costs."""

    kind: ProviderKind = "claude"
    model: str
    key_env: str | None = None  # env var holding the API key (never the key); default per kind
    endpoint: str | None = None  # base URL ending in /v1; default per kind; for claude: a proxy's base_url
    max_tokens: int = Field(default=1024, ge=1)
    price_in_per_m: float = Field(default=0.0, ge=0)  # USD per million input tokens
    price_out_per_m: float = Field(default=0.0, ge=0)  # USD per million output tokens
    headers: dict[str, str] = Field(default_factory=dict)  # extra HTTP headers (OpenRouter attribution, a proxy)
    dimensions: int | None = Field(default=None, ge=1)  # embed slots: the vector size the index expects
    floor: float | None = Field(default=None, ge=0, le=1)  # decide slots: under this score the candidate is not it
    extra_body: dict[str, Any] = Field(default_factory=dict)  # vendor fields merged into every request body

    @model_validator(mode="before")
    @classmethod
    def _infer_kind(cls, data: Any) -> Any:
        if isinstance(data, dict) and "kind" not in data:
            data = {**data, "kind": "openai_compat" if data.get("endpoint") else "claude"}
        return data

    @model_validator(mode="after")
    def _kind_defaults(self) -> ProviderConfig:
        info = self.info
        if self.endpoint is None:
            self.endpoint = info.endpoint
        if self.key_env is None:
            self.key_env = info.key_env
        if info.protocol == "openai" and not self.endpoint:
            raise ValueError(f"{self.kind} provider needs an endpoint")
        return self

    @property
    def info(self) -> KindInfo:
        return KINDS[self.kind]

    @property
    def protocol(self) -> Protocol:
        return self.info.protocol

    def key_state(self, env: Mapping[str, str]) -> KeyState:
        if not self.info.needs_key:
            return "not-needed"
        return "ok" if self.key_env and env.get(self.key_env) else "missing"

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return round((input_tokens * self.price_in_per_m + output_tokens * self.price_out_per_m) / 1_000_000, 6)


SlotTask = Literal["complete", "embed", "decide"]


class SlotConfig(BaseModel):
    """One job (planner, consolidate, embed, ...): which provider acts, which one shadows, and the choices."""

    task: SlotTask = "complete"  # embed: rpc.llm.embed (OpenAI-shaped vendors); decide: rpc.llm.decide (any kind)
    active: str
    shadow: str | None = None
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_providers(cls, data: Any) -> Any:
        """Lets the yaml stay flat: any key that is not active/shadow/providers is a provider."""
        if not isinstance(data, dict):
            return data
        out: dict[str, Any] = {"active": data.get("active"), "shadow": data.get("shadow")}
        if "task" in data:
            out["task"] = data["task"]
        providers = dict(data.get("providers") or {})
        for k, v in data.items():
            if k not in ("active", "shadow", "providers", "task"):
                providers[k] = v
        out["providers"] = providers
        return out

    @model_validator(mode="after")
    def _names_exist(self) -> SlotConfig:
        if self.active not in self.providers:
            raise ValueError(f"active provider {self.active!r} is not defined")
        if self.shadow is not None and self.shadow not in self.providers:
            raise ValueError(f"shadow provider {self.shadow!r} is not defined")
        if self.shadow == self.active:
            raise ValueError("shadow must differ from active")
        if self.task == "embed":
            for name, p in self.providers.items():
                if p.protocol != "openai":
                    raise ValueError(
                        f"provider {name!r} ({p.kind}) cannot embed; embed slots need an OpenAI-shaped vendor"
                    )
        return self


class GatewayConfig(BaseModel):
    """The whole providers.yaml: the slots plus the monthly budget."""

    budget_usd_month: float | None = Field(default=None, gt=0)
    slots: dict[str, SlotConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_slots(cls, data: Any) -> Any:
        """Lets the yaml stay flat: any key that is not budget_usd_month/slots is a slot."""
        if not isinstance(data, dict):
            return data
        out: dict[str, Any] = {"budget_usd_month": data.get("budget_usd_month")}
        slots = dict(data.get("slots") or {})
        for k, v in data.items():
            if k not in ("budget_usd_month", "slots"):
                slots[k] = v
        out["slots"] = slots
        return out

    @model_validator(mode="after")
    def _has_slots(self) -> GatewayConfig:
        if not self.slots:
            raise ValueError("no slots configured")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path, env: Mapping[str, str] | None = None) -> GatewayConfig:
        """Load providers.yaml; `${VAR}` and `${VAR:-default}` in it are filled from the environment first."""
        text = expand_env(Path(path).read_text(encoding="utf-8"), os.environ if env is None else env)
        return cls.model_validate(yaml.safe_load(text) or {})


_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(text: str, env: Mapping[str, str]) -> str:
    """Shell-style `${VAR}` / `${VAR:-default}`; an unset or empty variable takes the default (or nothing)."""

    def sub(m: re.Match[str]) -> str:
        value = env.get(m.group(1), "")
        return value if value != "" else (m.group(2) or "")

    return _ENV_RE.sub(sub, text)
