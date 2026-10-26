"""The in-memory index for unit tests, with a pg_trgm look-alike so fuzzy matching behaves like Postgres."""

from __future__ import annotations

import math
import re
from datetime import date

from ..schemas import EmbedTarget, Fact, FactRecord, Neighbour, NoteRecord, SummaryRecord, embedding_text
from .base import FUZZY_THRESHOLD


def _trigrams(text: str) -> set[str]:
    grams: set[str] = set()
    for word in re.findall(r"\w+", text.lower()):
        padded = f"  {word} "
        for i in range(len(padded) - 2):
            grams.add(padded[i : i + 3])
    return grams


def trigram_similarity(a: str, b: str) -> float:
    """Same recipe as pg_trgm: words padded with two leading and one trailing space, Jaccard on trigrams."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class InMemoryIndex:
    def __init__(self) -> None:
        self.notes: dict[str, NoteRecord] = {}
        self._facts: dict[str, list[FactRecord]] = {}
        self.summaries: dict[tuple[str, str], SummaryRecord] = {}
        self._hashes: dict[str, str] = {}
        self._vectors: dict[str, tuple[list[float], str]] = {}  # path -> (vector, model)

    async def body_hash(self, path: str) -> str | None:
        return self._hashes.get(path)

    async def upsert_note(self, record: NoteRecord, facts: list[Fact]) -> None:
        for existing in list(self.notes.values()):
            if existing.path == record.path and existing.name != record.name:
                await self.delete_note(existing.path)
        if (
            prev := next((r for r in self.notes.values() if r.path == record.path), None)
        ) and prev.body_hash != record.body_hash:
            self._vectors.pop(record.path, None)
        self.notes[record.name] = record
        self._facts[record.name] = [
            FactRecord(note=record.name, day=f.day, text=f.text, source=f.source) for f in facts
        ]
        self._hashes[record.path] = record.body_hash

    async def delete_note(self, path: str) -> None:
        for name, rec in list(self.notes.items()):
            if rec.path == path:
                del self.notes[name]
                self._facts.pop(name, None)
        self._hashes.pop(path, None)

    async def upsert_summary(self, record: SummaryRecord) -> None:
        if (prev := self.summaries.get((record.period, record.key))) and prev.body_hash != record.body_hash:
            self._vectors.pop(record.path, None)
        self.summaries[(record.period, record.key)] = record
        self._hashes[record.path] = record.body_hash

    async def get(self, name: str) -> NoteRecord | None:
        return self.notes.get(name.lower())

    async def by_alias(self, alias: str) -> list[NoteRecord]:
        a = alias.lower()
        return [r for r in self.notes.values() if a in r.aliases]

    async def fuzzy(self, text: str, limit: int = 3) -> list[tuple[NoteRecord, float]]:
        scored = []
        for r in self.notes.values():
            score = max([trigram_similarity(text, r.name)] + [trigram_similarity(text, a) for a in r.aliases])
            if score >= FUZZY_THRESHOLD:
                scored.append((r, score))
        scored.sort(key=lambda x: (-x[1], x[0].name))
        return scored[:limit]

    async def backlinks(self, name: str) -> list[NoteRecord]:
        n = name.lower()
        return [r for r in self.notes.values() if n in r.links]

    async def facts(self, name: str | None = None, day: date | None = None) -> list[FactRecord]:
        rows: list[FactRecord] = []
        for n, fs in self._facts.items():
            if name is not None and n != name.lower():
                continue
            rows.extend(f for f in fs if day is None or f.day == day)
        rows.sort(key=lambda f: f.day, reverse=True)
        return rows

    async def summary(self, period: str, key: str) -> SummaryRecord | None:
        return self.summaries.get((period, key))

    async def summaries_in(self, period: str, keys: list[str]) -> list[SummaryRecord]:
        found = [self.summaries.get((period, k)) for k in keys]
        return [s for s in found if s is not None]

    async def vocabulary(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for r in self.notes.values():
            out.append((r.name, r.name))
            out.extend((a, r.name) for a in r.aliases if a != r.name)
        return out

    # ---- embeddings ---------------------------------------------------------------------------

    def _rows(self) -> list[NoteRecord | SummaryRecord]:
        return [*self.notes.values(), *self.summaries.values()]

    async def stale_embeddings(self, model: str, limit: int = 200) -> list[EmbedTarget]:
        out: list[EmbedTarget] = []
        for r in self._rows():
            have = self._vectors.get(r.path)
            if have is None or have[1] != model:
                out.append(EmbedTarget(path=r.path, text=embedding_text(r)))
            if len(out) >= limit:
                break
        return out

    async def set_embedding(self, path: str, vector: list[float], model: str) -> None:
        self._vectors[path] = (list(vector), model)

    async def nearest(self, vector: list[float], limit: int = 8) -> list[Neighbour]:
        by_path = {r.path: r for r in self._rows()}
        scored = []
        for path, (v, _model) in self._vectors.items():
            if path in by_path:
                scored.append(Neighbour(record=by_path[path], score=round(_cosine(vector, v), 4)))
        scored.sort(key=lambda n: (-n.score, n.record.path))
        return scored[:limit]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
