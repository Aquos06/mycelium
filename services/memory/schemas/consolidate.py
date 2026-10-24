"""The nightly job's shapes (MEMORY.md §3): what the model returns, what memory sends, what it reports."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

from mycelium_sdk import Envelope

from .periods import Period
from .vault import NAME_RE, NoteType


def _slug(v: str) -> str:
    v = v.strip().lower()
    if not NAME_RE.match(v):
        raise ValueError(f"bad note slug {v!r}: lowercase letters, digits, '-' or '_', or CJK")
    return v


# ---- what the model returns ------------------------------------------------------------------------


class DigestFact(BaseModel):
    note: str = Field(description="entity slug, lowercase: mei, ramen-place-xinyi, hansen")
    type: NoteType | None = Field(default=None, description="only when the note is new")
    aliases: list[str] = Field(
        default_factory=list, description="other names in any language, when new or newly learned"
    )
    text: str = Field(min_length=1, description="one line, past tense, [[slug]] around other notes it mentions")
    events: list[int] = Field(default_factory=list, description="ids of the events this fact comes from")

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        return _slug(v)

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("text is required")
        return v

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for a in v:
            a = a.strip().lower()
            if a and a not in out:
                out.append(a)
        return out


class StateUpdate(BaseModel):
    note: str = Field(description="an existing note's slug")
    summary: str = Field(min_length=1, description="its new current state, one or two sentences")

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        return _slug(v)

    @field_validator("summary")
    @classmethod
    def _summary(cls, v: str) -> str:
        return " ".join(v.split())


class DayDigest(BaseModel):
    summary: str = Field(
        min_length=1, description="the day in three to six sentences, [[slug]] around every note mentioned"
    )
    facts: list[DigestFact] = Field(default_factory=list)
    updates: list[StateUpdate] = Field(default_factory=list, description="notes whose current state the day made stale")

    @field_validator("summary")
    @classmethod
    def _summary(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("summary is required")
        return v


# ---- what memory sends and keeps -------------------------------------------------------------------


class PeriodDigest(BaseModel):
    """What the model returns for a week or a month: one summary written from the day summaries."""

    summary: str = Field(
        min_length=1, description="the period in four to eight sentences, [[slug]] around every note that matters"
    )

    @field_validator("summary")
    @classmethod
    def _summary(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("summary is required")
        return v


class ModelRequest(BaseModel):
    """rpc.llm.complete as consolidation fills it (the gateway validates it again as CompletionRequest)."""

    slot: str
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    tool_choice: str
    max_tokens: int | None = Field(default=None, gt=0)  # None: the provider's setting
    cause: str | None = None
    timeout: float = Field(gt=0)


class RollupReport(BaseModel):
    """One week or month summary written from its day summaries; also the rpc.memory.rollup reply."""

    period: Period
    key: str  # 2026-W43 | 2026-10
    sources: int = 0  # day summaries the period had
    skipped: bool = False
    reason: str | None = None
    summary_path: str | None = None
    rounds: int = 0
    model: str | None = None
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None  # set when the rollup failed and the day's report carries it anyway


class ConsolidationReport(BaseModel):
    """One run for one day; also the rpc.memory.consolidate reply."""

    day: date
    events: int = 0
    skipped: bool = False
    reason: str | None = None
    summary_path: str | None = None
    facts_added: int = 0
    facts_skipped: int = 0
    notes_created: list[str] = Field(default_factory=list)
    notes_updated: list[str] = Field(default_factory=list)
    rounds: int = 0
    model: str | None = None
    cost_usd: float = 0.0
    latency_ms: int = 0
    rollups: list[RollupReport] = Field(default_factory=list)  # the week / month this day closed, if any


class RollupTrace(Envelope):
    """trace.rollup: one per week or month written, failed ones included."""

    source: str = "memory"
    ok: bool
    report: RollupReport
    error: str | None = None


class ConsolidateTrace(Envelope):
    """trace.consolidate: one per run, failed ones included."""

    source: str = "memory"
    ok: bool
    report: ConsolidationReport
    error: str | None = None
