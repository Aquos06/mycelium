"""The kinds of note in memory's vault. Memory files them by type; Main's `remember` tool offers the same list."""

from __future__ import annotations

from enum import StrEnum


class NoteType(StrEnum):
    SELF = "self"  # hansen.md
    PERSON = "person"
    PLACE = "place"
    PROJECT = "project"
    THING = "thing"
    ROUTINE = "routine"
    MODULE = "module"
