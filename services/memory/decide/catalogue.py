"""Round one's candidates: the index as a list of one-line entries, the way the scorer reads it."""

from __future__ import annotations

import re
import zlib
from datetime import date, timedelta

from ..index import Index
from ..schemas import DecideCandidate, FactRecord, NoteRecord, SummaryRecord, embedding_text

RECENT_DAYS = (
    14  # day summaries and facts older than this are reached through weeks, months and links, not the catalogue
)
MAX_FACTS = 150  # recent facts in the catalogue, newest first; with the notes and summaries this stays under one call
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


def candidate_text(record: NoteRecord | SummaryRecord) -> str:
    """The same line the embedder uses: a note by its name, aliases, type and state; a summary by its text."""
    return embedding_text(record)


def unlink(text: str) -> str:
    """[[slug|label]] -> label, [[slug]] -> slug; the words stay as written."""
    return " ".join(LINK_RE.sub(lambda m: m.group(2) or m.group(1), text).split())


def fact_candidate(note: NoteRecord, fact: FactRecord, via: str = "catalogue") -> DecideCandidate:
    """One dated fact as a candidate: picked, it shows on its note. The id is stable, so a fact scored from the
    catalogue is not proposed again as a hop."""
    day = fact.day.isoformat()
    return DecideCandidate(
        id=f"{note.path}#{day}#{zlib.crc32(fact.text.encode()) % 10000:04d}",
        path=note.path,
        text=f"{note.name}, {day}: {unlink(fact.text)}",
        via=via,
        excerpt=f"{day} {fact.text}",
    )


async def catalogue(index: Index, today: date, recent_days: int = RECENT_DAYS) -> list[DecideCandidate]:
    """Every note, every week and month summary, the day summaries of the last `recent_days`, and the dated facts
    of those days (newest first, at most MAX_FACTS): "how much was the dinner" lives in a fact, not a first paragraph."""
    since = today - timedelta(days=recent_days)
    rows = await index.catalogue(since=since)
    out = [DecideCandidate(id=r.path, path=r.path, text=candidate_text(r), via="catalogue") for r in rows]
    notes: dict[str, NoteRecord | None] = {}
    seen = {c.id for c in out}
    recent = await index.facts(since=since)
    facts = sorted(recent, key=lambda f: (-f.day.toordinal(), f.note, f.text))[:MAX_FACTS]  # newest first, then by note
    for f in facts:
        if f.note not in notes:
            notes[f.note] = await index.get(f.note)
        if (note := notes[f.note]) and (c := fact_candidate(note, f)).id not in seen:  # the same line twice: once
            seen.add(c.id)
            out.append(c)
    return out
