"""The files (MEMORY.md §1): a note per entity, a summary per day, week or month.

---
type: person
aliases: [mei, 小美]
---
First paragraph is the current state. It may contain [[links]].

- 2026-10-14 a dated fact, newest first, with provenance  (ev:48213)
- 2026-09-02 another one  (hansen)
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from mycelium_sdk import NoteType  # shared with Main's remember tool

__all__ = ["NAME_RE", "Fact", "Note", "NoteType", "Summary"]

# note names are file stems: lowercase slug or CJK, no separators that could leave the folder
NAME_RE = re.compile(r"^[a-z0-9぀-ヿ一-鿿][a-z0-9぀-ヿ一-鿿_-]{0,63}$")


class Fact(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: date
    text: str
    source: str | None = None  # ev:<id> | hansen | consolidation | sys


class Note(BaseModel):
    name: str
    path: str
    type: str  # a NoteType, but read from a file Hansen may have edited by hand
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    links: list[str] = Field(default_factory=list)  # derived from [[links]] in summary and facts
    facts: list[Fact] = Field(default_factory=list)


class Summary(BaseModel):
    period: str  # day | week | month
    key: str  # 2026-10-14 | 2026-W42 | 2026-10
    path: str
    text: str
    links: list[str] = Field(default_factory=list)
