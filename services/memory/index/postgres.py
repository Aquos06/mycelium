"""The Postgres index (asyncpg). `schema` lets tests, and later per-owner databases, keep their own tables."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from ..schemas import Fact, FactRecord, NoteRecord, SummaryRecord

SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
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
        return [FactRecord(note=r["note"], day=r["day"], text=r["text"], source=r["source"]) for r in rows]

    async def summary(self, period: str, key: str) -> SummaryRecord | None:
        row = await self.pool.fetchrow(
            f"SELECT period, key, path, text, links, body_hash FROM {self.s}.summaries WHERE period = $1 AND key = $2",
            period,
            key,
        )
        if not row:
            return None
        return SummaryRecord(
            period=row["period"],
            key=row["key"],
            path=row["path"],
            text=row["text"],
            links=list(row["links"] or []),
            body_hash=row["body_hash"],
        )

    async def vocabulary(self) -> list[tuple[str, str]]:
        rows = await self.pool.fetch(f"SELECT name, aliases FROM {self.s}.notes ORDER BY name")
        out: list[tuple[str, str]] = []
        for r in rows:
            out.append((r["name"], r["name"]))
            out.extend((a, r["name"]) for a in (r["aliases"] or []) if a != r["name"])
        return out
