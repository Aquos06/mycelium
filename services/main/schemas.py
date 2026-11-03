"""Main's messages and records: what it sends, what it publishes, what it holds while planning.

Say, Ask                 -> out.say, out.ask        (envelopes; `ref` on Ask is its own id)
PlanTrace                -> trace.plan              (one per handled message; votes attach by reply_id)
FeedbackTrace            -> trace.feedback
ModuleInfo, PackSummary, LlmCall: what the planner was given and what it cost, kept for the trace
BuildOutcome: how a build Main started ended (what it asks the builder is mycelium_sdk.build)

What it sends the planner model is the SDK's CompletionRequest (mycelium_sdk.llm).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mycelium_sdk import Envelope, Usage

from .tools import AskArgs, ToolOutcome

# ---- what Main sends ---------------------------------------------------------------------------------


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
    listens: list[str] = Field(default_factory=list)  # its manifest's subscribes: sense.chat = it hears every message


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


class LlmCall(BaseModel):
    """One planner round as the gateway reported it: what the trace keeps of a CompletionReply."""

    model: str | None = None
    usage: Usage | None = None
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
    proposal: str | None = None  # the module proposed, when the turn ended in a proposal (its card is the ask)
    error: str | None = None
    latency_ms: int = 0


# ---- what Main hears from the builder (the requests are the SDK's: mycelium_sdk.build) -----------------


class BuildOutcome(BaseModel):
    """How a build ended, from build.done / build.failed or from rpc.build.get on start."""

    build_id: str
    done: bool
    version: str | None = None
    stage: str | None = None  # where a failed build stopped
    error: str | None = None

    @classmethod
    def from_event(cls, subject: str, data: Mapping[str, Any]) -> BuildOutcome:
        return cls(
            build_id=str(data.get("build_id") or ""),
            done=subject == "build.done",
            version=data.get("version"),
            stage=data.get("stage"),
            error=data.get("error"),
        )

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> BuildOutcome | None:
        """A record of rpc.build.get; None while it is still queued or building."""
        if record.get("status") not in ("done", "failed"):
            return None
        return cls(
            build_id=str(record.get("id") or ""),
            done=record.get("status") == "done",
            version=record.get("version"),
            stage=record.get("stage"),
            error=record.get("error"),
        )


class FeedbackTrace(Envelope):
    source: str = "main"
    ref: str | None = None
    vote: int | None = None
    answer: str | None = None
    channel: str | None = None
    thread: str | None = None
