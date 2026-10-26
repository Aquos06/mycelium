"""The next round's candidates: one hop out from what the scorer just picked.

A neighbour may have been scored before and fallen under the floor: it comes back with its link as context
("linked from mei: ramen-place-xinyi, place. ..."), which is the point of the hop. A picked note also brings its
dated facts, one candidate each ("mei, 2026-09-02: recommended the book Project Hail Mary"); the recent ones were
in the catalogue already and the Decider does not score them twice. Only what is already picked is left out."""

from __future__ import annotations

from collections.abc import Iterable

from ..index import Index
from ..schemas import DecideCandidate, Pick
from .catalogue import candidate_text, fact_candidate

MAX_FACTS = 20  # per picked note, most recent first


async def expansion(index: Index, picks: Iterable[Pick], known: set[str]) -> list[DecideCandidate]:
    """What the picked notes link to, what links to them, the picked notes' facts, and what a picked summary links
    to; nothing in `known` (the picks so far, by id), each id once, the first way it was reached."""
    out: list[DecideCandidate] = []
    seen: set[str] = set(known)

    def add(c: DecideCandidate) -> None:
        if c.id not in seen:
            seen.add(c.id)
            out.append(c)

    for pick in picks:
        if pick.excerpt is not None:
            continue  # a fact: its note is already open, nothing further to hop to
        if pick.path.startswith("summaries/"):
            summary = await index.summary_by_path(pick.path)
            links, label, backlinks, facts = (summary.links if summary else []), pick.path, [], []
        else:
            note = await index.by_path(pick.path)
            if note is None:
                continue
            links, label = note.links, note.name
            backlinks = await index.backlinks(note.name)
            facts = [
                fact_candidate(note, f, via=f"fact on {f.day.isoformat()} of {note.name}")
                for f in (await index.facts(name=note.name))[:MAX_FACTS]
            ]
        for link in links:
            if target := await index.get(link):
                add(
                    DecideCandidate(
                        id=target.path, path=target.path, text=candidate_text(target), via=f"linked from {label}"
                    )
                )
        for back in backlinks:
            add(DecideCandidate(id=back.path, path=back.path, text=candidate_text(back), via=f"links to {label}"))
        for c in facts:
            add(c)
    return out
