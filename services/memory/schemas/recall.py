"""What the lookup ladder and recall return (MEMORY.md §4). The pack is what the planner reads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .index import NoteRecord


class Match(BaseModel):
    record: NoteRecord
    via: Literal["exact", "alias", "fuzzy"]
    score: float


class RecallItem(BaseModel):
    note: str  # the file path: people/mei.md, summaries/2026/10/14.md
    why: str  # why it was opened: "小美 is an alias of mei", "linked from ...", "yesterday"
    excerpt: str = ""


class RecallUsed(BaseModel):
    dates: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    embedding: bool = False  # M4


class RecallBudget(BaseModel):
    notes_opened: int
    max: int


class RecallPack(BaseModel):
    query: str
    items: list[RecallItem] = Field(default_factory=list)
    used: RecallUsed = Field(default_factory=RecallUsed)
    budget: RecallBudget
