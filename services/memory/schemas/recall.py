"""What the lookup ladder and recall return (MEMORY.md §4). The pack is what the planner reads."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from .decide import DecideUsed
from .index import NoteRecord


class MatchVia(StrEnum):
    """How a name in the query found its note."""

    EXACT = "exact"  # the note's own name
    ALIAS = "alias"
    FUZZY = "fuzzy"  # a capitalised word that looks like a name


class Match(BaseModel):
    record: NoteRecord
    via: MatchVia
    score: float


class RecallItem(BaseModel):
    note: str  # the file path: people/mei.md, summaries/2026/10/14.md
    why: str  # why it was opened: "小美 is an alias of mei", "linked from ...", "yesterday"
    excerpt: str = ""


class RecallUsed(BaseModel):
    dates: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)  # "week:2026-W42", "month:2026-10"
    embedding: bool = False  # the embedding rung ran
    decide: DecideUsed | None = None  # the decide step ran


class RecallBudget(BaseModel):
    notes_opened: int
    max: int


class RecallPack(BaseModel):
    query: str
    items: list[RecallItem] = Field(default_factory=list)
    used: RecallUsed = Field(default_factory=RecallUsed)
    budget: RecallBudget
