"""Main's messages and records: what it sends, what it publishes, what it holds while planning.

Say, Ask                 -> out.say, out.ask        (envelopes; `ref` on Ask is its own id; `blocks`: blocks.py)
Progress                 -> out.progress            (one message per job that changes in place: a build Main started)
PlanTrace                -> trace.plan              (one per handled message; votes attach by reply_id)
FeedbackTrace            -> trace.feedback
ModuleInfo, PackSummary, LlmCall: what the planner was given and what it cost, kept for the trace
BuildOutcome: how a build Main started ended (what it asks the builder is mycelium_sdk.build)

What it sends the planner model is the SDK's CompletionRequest (mycelium_sdk.llm).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mycelium_sdk import Envelope, RequestSpec, Usage
from mycelium_sdk.build import BuildDone, BuildFailed

from .blocks import Block
from .tools import AskArgs, ToolOutcome

# ---- what Main sends ---------------------------------------------------------------------------------


class Say(Envelope):
    source: str = "main"
    channel: str
    thread: str
    text: str
    blocks: list[Block] = Field(default_factory=list)  # a module's data under the text (blocks.py), in order


class Ask(Envelope):
    source: str = "main"
    channel: str
    thread: str
    text: str
    choices: list[str] = Field(min_length=2)
    ref: str  # what sense.feedback answers refer to: this message's own id
    blocks: list[Block] = Field(default_factory=list)


class StepState(StrEnum):
    DONE = "done"
    FAILED = "failed"
    ACTIVE = "active"
    PENDING = "pending"


class ProgressState(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ProgressStep(BaseModel):
    text: str
    state: StepState
    since: str | None = None  # an active step: when it began, so a reader can show how long it has taken


class Progress(Envelope):
    """out.progress: a job Hansen is waiting on, as one message that changes in place. Every update of a job
    carries the same `ref` and the whole picture, and replaces the one before: a reader keeps the one that is
    finished, else the highest `seq` (two updates can arrive in either order)."""

    source: str = "main"
    channel: str
    thread: str
    ref: str  # the job: a build's id
    seq: int = 0
    title: str
    state: ProgressState
    steps: list[ProgressStep] = Field(default_factory=list)
    text: str  # the same in plain lines, for a channel that shows only text


# ---- what the planner was given --------------------------------------------------------------------


class ModuleInfo(BaseModel):
    name: str
    purpose: str = ""
    requests: list[str] = Field(default_factory=list)  # "<module>.<action>", as the planner must call them
    listens: list[str] = Field(default_factory=list)  # its manifest's subscribes: sense.chat = it hears every message
    specs: dict[str, RequestSpec] = Field(default_factory=dict)  # "<module>.<action>" -> what it takes and returns
    status: str = "running"  # the supervisor's: a stopped or retired module is listed as not running, never called
    version: str = ""
    grown: bool = False  # the builder grew it (GROWN_DIR), so `change_module` can change it


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
    claim_check: bool = False  # a reply said something was saved that no `remember` did, so Main asked again
    error: str | None = None
    latency_ms: int = 0


# ---- what Main hears from the builder (the requests are the SDK's: mycelium_sdk.build) -----------------


class BuildOutcome(BaseModel):
    """How a build ended, as Main tells it: from build.done / build.failed, or from its record (rpc.build.get) when
    Main missed the event, or "unknown" when the builder lost it."""

    build_id: str
    done: bool
    version: str | None = None
    stage: str | None = None  # where a failed build stopped
    error: str | None = None

    @classmethod
    def of(cls, ev: BuildDone | BuildFailed) -> BuildOutcome:
        if isinstance(ev, BuildDone):
            return cls(build_id=ev.build_id, done=True, version=ev.version)
        return cls(build_id=ev.build_id, done=False, stage=ev.stage.value, error=ev.error)


class FeedbackTrace(Envelope):
    source: str = "main"
    ref: str | None = None
    vote: int | None = None
    answer: str | None = None
    channel: str | None = None
    thread: str | None = None
