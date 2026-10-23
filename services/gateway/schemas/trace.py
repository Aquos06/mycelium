"""What the gateway publishes on trace.*.

    trace.llm          LlmTrace     one per call, also the failed and the budget-refused ones, and
                                    shadow runs (shadow=true): metadata and cost only, never text
    trace.llm.shadow   ShadowTrace  active vs shadow result for one call; carries both texts,
                                    because comparing them is its whole point

Both are envelopes (id, ts, source, cause, hops): `cause` is the event the call served, so the
tracer files them next to Main's trace.plan for the same turn.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mycelium_sdk import Envelope

from .completion import Usage


class LlmTrace(Envelope):
    source: str = "gateway"
    slot: str
    provider: str
    model: str | None = None
    ok: bool
    latency_ms: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    usage: Usage | None = None
    stop_reason: str | None = None
    tool_calls: list[str] = Field(default_factory=list)  # names only
    tools_offered: list[str] = Field(default_factory=list)
    error: str | None = None
    shadow: bool = False  # a shadow run: billed and logged like any call, its result discarded


class ShadowSide(BaseModel):
    """What the active provider answered, reduced to what the comparison needs."""

    text: str = ""
    tool_calls: list[str] = Field(default_factory=list)


class ShadowResult(ShadowSide):
    """The same for the shadow provider, plus who it was."""

    provider: str
    model: str
    latency_ms: int = Field(default=0, ge=0)


class ShadowTrace(Envelope):
    source: str = "gateway"
    slot: str
    active: ShadowSide
    shadow: ShadowResult
    agree: bool

    @staticmethod
    def agrees(active: ShadowSide, shadow: ShadowSide) -> bool:
        """Same tools in the same order, and both spoke or both stayed silent."""
        return active.tool_calls == shadow.tool_calls and bool(active.text) == bool(shadow.text)
