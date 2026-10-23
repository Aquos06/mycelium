"""Rows of the index (MEMORY.md §2): what the indexer writes and recall reads."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteRecord(BaseModel):
    name: str
    path: str
    type: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    links: list[str] = Field(default_factory=list)
    body_hash: str = ""
    updated_at: datetime | None = None


class FactRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    note: str
    day: date
    text: str
    source: str | None = None


class SummaryRecord(BaseModel):
    period: str
    key: str
    path: str
    text: str
    links: list[str] = Field(default_factory=list)
    body_hash: str = ""


class IndexStats(BaseModel):
    """One pass of the indexer over the vault; also the rpc.memory.reindex reply."""

    notes: int = 0
    summaries: int = 0
    skipped: int = 0
