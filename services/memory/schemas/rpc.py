"""rpc.memory.* requests and replies: the contract Main and mctl code against.

    rpc.memory.remember     RememberRequest   -> RememberReply
    rpc.memory.lookup       LookupRequest     -> LookupReply
    rpc.memory.recall       RecallRequest     -> RecallPack (recall.py)
    rpc.memory.reindex      {}                -> IndexStats (index.py)
    rpc.memory.consolidate  ConsolidateRequest -> ConsolidationReport (consolidate.py)

The handler adds ok=true; errors are {"ok": false, "error": "<field>: <message>"}.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from .vault import NAME_RE, NoteType

DEFAULT_BUDGET = 8


def _collapse(text: str) -> str:
    return " ".join(text.split())


class FactIn(BaseModel):
    text: str = Field(min_length=1)
    day: date | None = None  # default: today

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        v = _collapse(v)
        if not v:
            raise ValueError("fact.text is required")
        return v


class RememberRequest(BaseModel):
    note: str
    type: NoteType | None = None  # used only when the note does not exist yet
    aliases: list[str] = Field(default_factory=list)
    summary: str | None = None  # replaces the note's first paragraph
    fact: FactIn | None = None
    source: str | None = None  # ev:<id> | hansen | consolidation | sys

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        v = v.strip().lower()
        if not NAME_RE.match(v):
            raise ValueError(f"bad note name: {v!r}")
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

    @field_validator("summary")
    @classmethod
    def _summary(cls, v: str | None) -> str | None:
        return _collapse(v) if v is not None else None

    @model_validator(mode="after")
    def _something_to_remember(self) -> RememberRequest:
        if self.fact is None and not self.summary:
            raise ValueError("a fact or a summary is required")
        return self


class RememberReply(BaseModel):
    path: str
    created: bool


class LookupRequest(BaseModel):
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        return v


class LookupMatch(BaseModel):
    name: str
    path: str
    type: str
    via: str  # exact | alias | fuzzy
    score: float


class LookupReply(BaseModel):
    matches: list[LookupMatch] = Field(default_factory=list)


class RecallRequest(BaseModel):
    query: str = Field(min_length=1)
    budget: int = Field(default=DEFAULT_BUDGET, ge=1, le=50)
    today: date | None = None  # for replays and tests; default: the service's clock

    @field_validator("query")
    @classmethod
    def _query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query is required")
        return v


class ConsolidateRequest(BaseModel):
    day: date | None = None  # default: yesterday by the service's clock
