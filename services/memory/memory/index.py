"""The index: a searchable copy of the vault. Only the indexer writes it; drop it and re-run to rebuild.

Two implementations behind one protocol, like the bus and the registry: InMemoryIndex for unit tests
(with a pure-Python pg_trgm look-alike so fuzzy matching behaves the same), PostgresIndex for real.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from .vault import Fact

FUZZY_THRESHOLD = 0.3  # pg_trgm's default similarity_threshold
SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


@dataclass
class NoteRecord:
    name: str
    path: str
    type: str
    aliases: list[str] = field(default_factory=list)
    summary: str = ""
    links: list[str] = field(default_factory=list)
    body_hash: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True)
class FactRecord:
    note: str
    day: date
    text: str
    source: str | None = None


@dataclass
class SummaryRecord:
    period: str
    key: str
    path: str
    text: str
    links: list[str] = field(default_factory=list)
    body_hash: str = ""


class Index(Protocol):
    async def body_hash(self, path: str) -> str | None: ...
    async def upsert_note(self, record: NoteRecord, facts: list[Fact]) -> None: ...
    async def delete_note(self, path: str) -> None: ...
    async def upsert_summary(self, record: SummaryRecord) -> None: ...
    async def get(self, name: str) -> NoteRecord | None: ...
    async def by_alias(self, alias: str) -> list[NoteRecord]: ...
    async def fuzzy(self, text: str, limit: int = 3) -> list[tuple[NoteRecord, float]]: ...
    async def backlinks(self, name: str) -> list[NoteRecord]: ...
    async def facts(self, name: str | None = None, day: date | None = None) -> list[FactRecord]: ...
    async def summary(self, period: str, key: str) -> SummaryRecord | None: ...
    async def vocabulary(self) -> list[tuple[str, str]]: ...


# ---- pg_trgm look-alike -------------------------------------------------------------------


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


# ---- in-memory ----------------------------------------------------------------------------


class InMemoryIndex:
    def __init__(self) -> None:
        self.notes: dict[str, NoteRecord] = {}
        self._facts: dict[str, list[FactRecord]] = {}
        self.summaries: dict[tuple[str, str], SummaryRecord] = {}
        self._hashes: dict[str, str] = {}

    async def body_hash(self, path: str) -> str | None:
        return self._hashes.get(path)

    async def upsert_note(self, record: NoteRecord, facts: list[Fact]) -> None:
        for existing in list(self.notes.values()):
            if existing.path == record.path and existing.name != record.name:
                await self.delete_note(existing.path)
        self.notes[record.name] = record
        self._facts[record.name] = [FactRecord(record.name, f.day, f.text, f.source) for f in facts]
        self._hashes[record.path] = record.body_hash

    async def delete_note(self, path: str) -> None:
        for name, rec in list(self.notes.items()):
            if rec.path == path:
                del self.notes[name]
                self._facts.pop(name, None)
        self._hashes.pop(path, None)

    async def upsert_summary(self, record: SummaryRecord) -> None:
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

    async def vocabulary(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for r in self.notes.values():
            out.append((r.name, r.name))
            out.extend((a, r.name) for a in r.aliases if a != r.name)
        return out


# ---- postgres -----------------------------------------------------------------------------

SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")

NOTE_COLS = "name, path, type, aliases, summary, body_hash, updated_at"


def _note(row: Any, links: list[str] | None = None) -> NoteRecord:
    return NoteRecord(
        name=row["name"],
        path=row["path"],
        type=row["type"],
        aliases=list(row["aliases"] or []),
        summary=row["summary"],
        links=links or [],
        body_hash=row["body_hash"],
        updated_at=row["updated_at"],
    )


class PostgresIndex:
    """Backed by asyncpg. `schema` lets tests (and later, per-owner databases) keep their own tables."""

    def __init__(self, pool, schema: str = "memory") -> None:
        if not SCHEMA_RE.match(schema):
            raise ValueError(f"bad schema name: {schema!r}")
        self.pool = pool
        self.s = schema

    async def ensure_schema(self) -> None:
        await self.pool.execute(SCHEMA_SQL.replace("{schema}", self.s))

    async def _links_for(self, conn, note_ids: list[int]) -> dict[int, list[str]]:
        if not note_ids:
            return {}
        rows = await conn.fetch(
            f"SELECT from_note, to_name FROM {self.s}.links WHERE from_note = ANY($1::bigint[]) ORDER BY ord", note_ids
        )
        out: dict[int, list[str]] = {i: [] for i in note_ids}
        for r in rows:
            out[r["from_note"]].append(r["to_name"])
        return out

    async def _notes(self, sql: str, *args: Any) -> list[NoteRecord]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            links = await self._links_for(conn, [r["id"] for r in rows])
            return [_note(r, links.get(r["id"])) for r in rows]

    async def body_hash(self, path: str) -> str | None:
        row = await self.pool.fetchrow(
            f"SELECT body_hash FROM {self.s}.notes WHERE path = $1 UNION ALL SELECT body_hash FROM {self.s}.summaries WHERE path = $1 LIMIT 1",
            path,
        )
        return row["body_hash"] if row else None

    async def upsert_note(self, record: NoteRecord, facts: list[Fact]) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(f"DELETE FROM {self.s}.notes WHERE path = $1 AND name <> $2", record.path, record.name)
            note_id = await conn.fetchval(
                f"""INSERT INTO {self.s}.notes (name, path, type, aliases, summary, body_hash, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, now())
                    ON CONFLICT (name) DO UPDATE SET path = EXCLUDED.path, type = EXCLUDED.type, aliases = EXCLUDED.aliases,
                        summary = EXCLUDED.summary, body_hash = EXCLUDED.body_hash, updated_at = now()
                    RETURNING id""",
                record.name,
                record.path,
                record.type,
                record.aliases,
                record.summary,
                record.body_hash,
            )
            await conn.execute(f"DELETE FROM {self.s}.links WHERE from_note = $1", note_id)
            await conn.execute(f"DELETE FROM {self.s}.facts WHERE note_id = $1", note_id)
            if record.links:
                await conn.executemany(
                    f"INSERT INTO {self.s}.links (from_note, to_name, ord) VALUES ($1, $2, $3)",
                    [(note_id, link, i) for i, link in enumerate(record.links)],
                )
            if facts:
                await conn.executemany(
                    f"INSERT INTO {self.s}.facts (note_id, day, text, source) VALUES ($1, $2, $3, $4)",
                    [(note_id, f.day, f.text, f.source) for f in facts],
                )

    async def delete_note(self, path: str) -> None:
        await self.pool.execute(f"DELETE FROM {self.s}.notes WHERE path = $1", path)

    async def upsert_summary(self, record: SummaryRecord) -> None:
        await self.pool.execute(
            f"""INSERT INTO {self.s}.summaries (period, key, path, text, links, body_hash)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (period, key) DO UPDATE SET path = EXCLUDED.path, text = EXCLUDED.text,
                    links = EXCLUDED.links, body_hash = EXCLUDED.body_hash""",
            record.period,
            record.key,
            record.path,
            record.text,
            record.links,
            record.body_hash,
        )

    async def get(self, name: str) -> NoteRecord | None:
        rows = await self._notes(f"SELECT id, {NOTE_COLS} FROM {self.s}.notes WHERE name = $1", name.lower())
        return rows[0] if rows else None

    async def by_alias(self, alias: str) -> list[NoteRecord]:
        return await self._notes(
            f"SELECT id, {NOTE_COLS} FROM {self.s}.notes WHERE $1 = ANY(aliases) ORDER BY name", alias.lower()
        )

    async def fuzzy(self, text: str, limit: int = 3) -> list[tuple[NoteRecord, float]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT id, {NOTE_COLS},
                           GREATEST(similarity(name, $1),
                                    COALESCE((SELECT max(similarity(a, $1)) FROM unnest(aliases) a), 0)) AS score
                    FROM {self.s}.notes
                    WHERE name % $1 OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE a % $1)
                    ORDER BY score DESC, name LIMIT $2""",
                text.lower(),
                limit,
            )
            links = await self._links_for(conn, [r["id"] for r in rows])
            return [(_note(r, links.get(r["id"])), float(r["score"])) for r in rows]

    async def backlinks(self, name: str) -> list[NoteRecord]:
        return await self._notes(
            f"""SELECT n.id, {", ".join("n." + c for c in NOTE_COLS.split(", "))}
                FROM {self.s}.links l JOIN {self.s}.notes n ON n.id = l.from_note
                WHERE l.to_name = $1 ORDER BY n.name""",
            name.lower(),
        )

    async def facts(self, name: str | None = None, day: date | None = None) -> list[FactRecord]:
        rows = await self.pool.fetch(
            f"""SELECT n.name AS note, f.day, f.text, f.source
                FROM {self.s}.facts f JOIN {self.s}.notes n ON n.id = f.note_id
                WHERE ($1::text IS NULL OR n.name = $1) AND ($2::date IS NULL OR f.day = $2)
                ORDER BY f.day DESC, f.id""",
            name.lower() if name else None,
            day,
        )
        return [FactRecord(r["note"], r["day"], r["text"], r["source"]) for r in rows]

    async def summary(self, period: str, key: str) -> SummaryRecord | None:
        row = await self.pool.fetchrow(
            f"SELECT period, key, path, text, links, body_hash FROM {self.s}.summaries WHERE period = $1 AND key = $2",
            period,
            key,
        )
        if not row:
            return None
        return SummaryRecord(
            row["period"], row["key"], row["path"], row["text"], list(row["links"] or []), row["body_hash"]
        )

    async def vocabulary(self) -> list[tuple[str, str]]:
        rows = await self.pool.fetch(f"SELECT name, aliases FROM {self.s}.notes ORDER BY name")
        out: list[tuple[str, str]] = []
        for r in rows:
            out.append((r["name"], r["name"]))
            out.extend((a, r["name"]) for a in (r["aliases"] or []) if a != r["name"])
        return out
