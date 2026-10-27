"""Main's messages and records: what it sends, what it publishes, what it holds while planning.

PlannerRequest           -> rpc.llm.complete (the gateway validates it again as CompletionRequest)
Say, Ask                 -> out.say, out.ask        (envelopes; `ref` on Ask is its own id)
PlanTrace                -> trace.plan              (one per handled message; votes attach by reply_id)
FeedbackTrace            -> trace.feedback
ModuleInfo, PackSummary, LlmCall: what the planner was given and what it cost, kept for the trace
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mycelium_sdk import Envelope

from .tools import AskArgs, ToolOutcome

# ---- what Main sends ---------------------------------------------------------------------------------


class PlannerRequest(BaseModel):
    slot: str = "planner"
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    cause: str | None = None  # the message this turn answers
    hops: int = Field(default=0, ge=0)  # that message's hops
    timeout: float = Field(gt=0)  # seconds Main waits; the gateway gives up first
    stream: bool = True  # the gateway publishes the text on stream.llm as it is written; the web app shows it by cause


class Say(Envelope):
    source: str = "main"
    channel: str
    thread: str
    text: str


class Ask(Envelope):
    source: str = "main"
    channel: str
    thread: str
    text: str
    choices: list[str] = Field(min_length=2)
    ref: str  # what sense.feedback answers refer to: this message's own id


# ---- what the planner was given --------------------------------------------------------------------


class ModuleInfo(BaseModel):
    name: str
    purpose: str = ""
    requests: list[str] = Field(default_factory=list)  # "<module>.<action>", as the planner must call them


class PackItem(BaseModel):
    note: str
    why: str


class RecallUsed(BaseModel):
    model_config = ConfigDict(extra="allow")  # memory's own detail; kept as it came

    dates: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    embedding: bool = False


class PackSummary(BaseModel):
    """The recall pack without the excerpts: enough to see what the planner was shown and why."""

    items: list[PackItem] = Field(default_factory=list)
    used: RecallUsed | None = None

    @classmethod
    def from_reply(cls, pack: Mapping[str, Any] | None) -> PackSummary:
        pack = pack or {}
        return cls(
            items=[PackItem(note=i["note"], why=i["why"]) for i in pack.get("items") or []],
            used=RecallUsed.model_validate(pack["used"]) if pack.get("used") else None,
        )


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LlmCall(BaseModel):
    """One planner round as the gateway reported it (extra reply fields are ignored)."""

    model: str | None = None
    usage: TokenUsage | None = None
    cost_usd: float = 0.0


# ---- what Main publishes ---------------------------------------------------------------------------


class SayOutput(BaseModel):
    say: str


class AskOutput(BaseModel):
    ask: AskArgs


class PlanTrace(Envelope):
    source: str = "main"
    channel: str
    thread: str
    input: str
    pack: PackSummary
    recall_error: str | None = None
    modules: list[str] = Field(default_factory=list)
    tools: list[ToolOutcome] = Field(default_factory=list)
    llm_calls: list[LlmCall] = Field(default_factory=list)
    cost_usd: float = 0.0
    rounds: int = 0
    output: SayOutput | AskOutput
    reply_id: str  # the out.say / out.ask id; the tracer attaches votes by it
    error: str | None = None
    latency_ms: int = 0


class FeedbackTrace(Envelope):
    source: str = "main"
    ref: str | None = None
    vote: int | None = None
    answer: str | None = None
    channel: str | None = None
    thread: str | None = None
