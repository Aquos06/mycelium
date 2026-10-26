"""The decide step (MEMORY.md §4): which notes is a vague question about, and where to hop from them.

DecideCandidate  one row the scorer may pick: its path, the text that stands for it, how it became a candidate
DecideCall       rpc.llm.decide as memory fills it (the gateway validates it again as DecideRequest)
Pick             a candidate the scorer put above the floor, with its round and score
DecideReport     one run of the loop; also what the pack and trace.decide carry
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mycelium_sdk import Envelope


class DecideCandidate(BaseModel):
    id: str  # what the scorer sees: a note's or summary's path, or "<path>#<day>#<n>" for one of its facts
    path: str  # the file to open when picked
    text: str
    via: str  # "catalogue" | "linked from mei" | "links to mei" | "fact on 2026-10-14 of mei"
    excerpt: str | None = None  # a fact candidate: the dated line to show when it is picked


class DecideCall(BaseModel):
    slot: str = "decide"
    query: str
    candidates: list[dict[str, str]] = Field(min_length=1)  # [{id, text}]
    cause: str | None = None
    timeout: float = Field(gt=0)


class Pick(BaseModel):
    id: str
    path: str
    score: float = Field(ge=0.0, le=1.0)
    round: int = Field(ge=1)
    via: str
    excerpt: str | None = None  # set for a fact: recall shows this line on the note


class DecideReport(BaseModel):
    floor: float | None = None  # the floor used: MEMORY_DECIDE_FLOOR, else the scorer's own
    seeds: int = 0  # notes the exact rungs opened; round one hops out from them instead of scoring the catalogue
    rounds: int = 0
    calls: int = 0  # rpc.llm.decide requests made
    scored: int = 0  # candidates scored, all rounds
    picked: list[Pick] = Field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None  # the loop stopped early; picks made before it stay


class DecideUsed(BaseModel):
    """What the recall pack says about the decide step."""

    floor: float | None = None
    seeds: int = 0
    rounds: int
    calls: int
    scored: int
    picked: int
    model: str | None = None
    latency_ms: int = 0
    error: str | None = None


class DecideTrace(Envelope):
    """trace.decide: one per run of the loop."""

    source: str = "memory"
    query: str
    ok: bool
    report: DecideReport
    error: str | None = None
