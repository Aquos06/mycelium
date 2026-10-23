"""Recall: which notes should the planner get to read for this question?

Dates, then names, then one hop of links, then (later) embeddings. Ordinary code: the same question
opens the same notes, and the pack says why each one was opened.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel

from .index import FUZZY_THRESHOLD, Index, NoteRecord
from .vault import Vault

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
DATE_RE = re.compile(
    r"\b(?P<iso>\d{4}-\d{2}-\d{2})\b|\b(?P<today>today)\b|\b(?P<yesterday>yesterday)\b|\blast (?P<weekday>"
    + "|".join(WEEKDAYS)
    + r")\b",
    re.IGNORECASE,
)
# words that are capitalised in ordinary English and must never be fuzzy-matched into a person
FUZZY_STOPWORDS = set(WEEKDAYS) | {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "today",
    "yesterday",
    "tomorrow",
    "what",
    "who",
    "when",
    "where",
    "why",
    "how",
    "did",
    "does",
    "remember",
    "tell",
    "show",
}
CJK_RE = re.compile(r"[぀-ヿ一-鿿]")
EXCERPT_CHARS = 240


def resolve_dates(query: str, today: date) -> list[tuple[str, date]]:
    """Every date expression in the query, in order of appearance, as (phrase as written, date)."""
    out: list[tuple[str, date]] = []
    for m in DATE_RE.finditer(query):
        phrase = m.group(0)
        if m.group("iso"):
            try:
                out.append((phrase, date.fromisoformat(m.group("iso"))))
            except ValueError:
                continue
        elif m.group("today"):
            out.append((phrase, today))
        elif m.group("yesterday"):
            out.append((phrase, today - timedelta(days=1)))
        elif m.group("weekday"):
            # the most recent such weekday strictly before today; same weekday as today means a week ago
            delta = (today.weekday() - WEEKDAYS[m.group("weekday").lower()]) % 7 or 7
            out.append((phrase, today - timedelta(days=delta)))
    return out


def _term_positions(term: str, query_lower: str) -> int:
    if CJK_RE.search(term):
        return query_lower.find(term)
    m = re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", query_lower)
    return m.start() if m else -1


async def find_names(query: str, index: Index) -> list[tuple[str, str, str]]:
    """Names and aliases present in the query -> (term, note name, exact|alias|fuzzy), in query order.

    Fuzzy matching runs only on capitalised words that nothing matched exactly, so ordinary words
    never turn into people.
    """
    q = query.lower()
    hits: list[tuple[int, int, str, str, str]] = []
    for term, name in await index.vocabulary():
        pos = _term_positions(term, q)
        if pos >= 0:
            hits.append((pos, -len(term), term, name, "exact" if term == name else "alias"))
    hits.sort()

    found: list[tuple[str, str, str]] = []
    taken: list[tuple[int, int]] = []
    names: set[str] = set()
    for pos, neglen, term, name, via in hits:
        end = pos - neglen
        if name in names or any(pos < e and end > s for s, e in taken):
            continue
        found.append((term, name, via))
        taken.append((pos, end))
        names.add(name)

    for m in re.finditer(r"\b[A-Z][a-z]{2,}\b", query):
        if m.group(0).lower() in FUZZY_STOPWORDS or any(m.start() < e and m.end() > s for s, e in taken):
            continue
        candidates = await index.fuzzy(m.group(0).lower(), limit=1)
        if candidates and candidates[0][1] >= FUZZY_THRESHOLD and candidates[0][0].name not in names:
            found.append((m.group(0).lower(), candidates[0][0].name, "fuzzy"))
            names.add(candidates[0][0].name)
    return found


class Match(BaseModel):
    record: NoteRecord
    via: str  # exact | alias | fuzzy
    score: float


async def lookup(index: Index, name: str) -> list[Match]:
    """The lookup ladder for one name: exact -> alias -> fuzzy. Stops at the first rung that matches."""
    if r := await index.get(name):
        return [Match(record=r, via="exact", score=1.0)]
    if rs := await index.by_alias(name):
        return [Match(record=r, via="alias", score=1.0) for r in rs]
    return [Match(record=r, via="fuzzy", score=round(score, 3)) for r, score in await index.fuzzy(name, limit=3)]


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 1].rstrip() + "…"


async def _excerpt(index: Index, record: NoteRecord, days: list[date], words: set[str]) -> str:
    """Facts on the days asked about win; then facts mentioning query words; then the note's summary."""
    facts = await index.facts(name=record.name)
    on_days = [f for f in facts if f.day in days]
    mentions = [f for f in facts if any(w in f.text.lower() for w in words)]
    chosen = on_days or mentions
    if chosen:
        return _clip(" · ".join(f"{f.day.isoformat()} {f.text}" for f in chosen[:3]))
    return _clip(record.summary)


async def recall(vault: Vault, index: Index, query: str, today: date, budget: int = 8) -> dict[str, Any]:
    items: list[dict[str, str]] = []
    opened: set[str] = set()
    used: dict[str, Any] = {"dates": [], "names": [], "embedding": False}
    words = {w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3}
    days: list[date] = []

    def add(path: str, why: str, excerpt: str) -> bool:
        if len(items) >= budget or path in opened:
            return False
        items.append({"note": path, "why": why, "excerpt": excerpt})
        opened.add(path)
        return True

    async def add_note(record: NoteRecord, why: str) -> bool:
        return add(record.path, why, await _excerpt(index, record, days, words))

    async def hop(from_path: str, links: list[str]) -> None:
        for link in links:
            if target := await index.get(link):
                await add_note(target, f"linked from {from_path}")

    # 1. dates: the day summary, what it links to, then anything else with a fact that day
    for phrase, d in resolve_dates(query, today):
        used["dates"].append(d.isoformat())
        days.append(d)
        s = await index.summary("day", d.isoformat())
        if s:
            add(s.path, f"{phrase} = {d.isoformat()}", _clip(s.text))
            await hop(s.path, s.links)
        for f in await index.facts(day=d):
            if record := await index.get(f.note):
                await add_note(record, f"has a fact on {d.isoformat()}")

    # 2. names: the note, then one hop
    for term, name, via in await find_names(query, index):
        used["names"].append(name)
        record = await index.get(name)
        if record is None:
            continue
        why = {
            "exact": f"{name} named in the query",
            "alias": f"{term} is an alias of {name}",
            "fuzzy": f"{term} looks like {name}",
        }[via]
        await add_note(record, why)
        await hop(record.path, record.links)

    # 3. the recent past is always context
    for why, d in (("today", today), ("yesterday", today - timedelta(days=1))):
        if s := await index.summary("day", d.isoformat()):
            add(s.path, why, _clip(s.text))

    # 4. embeddings: not wired yet (M4); the pack says so
    return {"query": query, "items": items, "used": used, "budget": {"notes_opened": len(items), "max": budget}}
