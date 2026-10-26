"""rpc.llm.config: the loaded providers.yaml as the settings page reads it. Key states, never keys."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .config import KeyState, ProviderKind


class ProviderInfo(BaseModel):
    kind: ProviderKind
    model: str
    endpoint: str | None = None
    key_env: str | None = None
    key_state: KeyState
    max_tokens: int
    price_in_per_m: float
    price_out_per_m: float


class SlotInfo(BaseModel):
    task: str = "complete"
    active: str
    shadow: str | None = None
    providers: dict[str, ProviderInfo] = Field(default_factory=dict)


class ConfigReply(BaseModel):
    budget_usd_month: float | None = None
    slots: dict[str, SlotInfo] = Field(default_factory=dict)
