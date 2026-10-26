"""The Postgres index: SQLAlchemy Core over the async engine. `schema` lets tests, and later per-owner
databases, keep their own tables; ensure_schema() runs memory's Alembic tree into it."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import any_, bindparam, delete, func, insert, literal_column, or_, select, text, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from mycelium_sdk.db import migrate

from ..schemas import EmbedTarget, Fact, FactRecord, Neighbour, NoteRecord, SummaryRecord, embedding_text
from .tables import EMBEDDING_DIMENSIONS, IndexTables, Vector

SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


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
    def __init__(self, engine: AsyncEngine, schema: str = "memory") -> None:
        if not SCHEMA_RE.match(schema):
            raise ValueError(f"bad schema name: {schema!r}")
        self.engine = engine
        self.s = schema
        self.t = IndexTables(schema)

    async def ensure_schema(self) -> None:
        await migrate(self.engine, MIGRATIONS, schema=self.s)

    async def _links_for(self, conn, note_ids: list[int]) -> dict[int, list[str]]:
        if not note_ids:
            return {}
        links = self.t.links
        rows = await conn.execute(
            select(links.c.from_note, links.c.to_name).where(links.c.from_note.in_(note_ids)).order_by(links.c.ord)
        )
        out: dict[int, list[str]] = {i: [] for i in note_ids}
        for from_note, to_name in rows:
            out[from_note].append(to_name)
        return out

    async def _notes(self, stmt) -> list[NoteRecord]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
            links = await self._links_for(conn, [r["id"] for r in rows])
            return [_note(r, links.get(r["id"])) for r in rows]

    async def body_hash(self, path: str) -> str | None:
        n, s = self.t.notes, self.t.summaries
        stmt = union_all(
            select(n.c.body_hash).where(n.c.path == path), select(s.c.body_hash).where(s.c.path == path)
        ).limit(1)
        async with self.engine.connect() as conn:
            return (await conn.execute(stmt)).scalar()

    async def upsert_note(self, record: NoteRecord, facts: list[Fact]) -> None:
        n, links, f = self.t.notes, self.t.links, self.t.facts
        async with self.engine.begin() as conn:
            await conn.execute(delete(n).where(n.c.path == record.path, n.c.name != record.name))
            stmt = pg_insert(n).values(
                name=record.name,
                path=record.path,
                type=record.type,
                aliases=record.aliases,
                summary=record.summary,
                body_hash=record.body_hash,
                updated_at=func.now(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[n.c.name],
                set_={
                    "path": stmt.excluded.path,
                    "type": stmt.excluded.type,
                    "aliases": stmt.excluded.aliases,
                    "summary": stmt.excluded.summary,
                    "body_hash": stmt.excluded.body_hash,
                    "updated_at": func.now(),
                    "embedding": None,  # the text changed: re-embed
                    "embedding_model": None,
                },
            ).returning(n.c.id)
            note_id = (await conn.execute(stmt)).scalar_one()
            await conn.execute(delete(links).where(links.c.from_note == note_id))
            await conn.execute(delete(f).where(f.c.note_id == note_id))
            if record.links:
                await conn.execute(
                    insert(links),
                    [{"from_note": note_id, "to_name": link, "ord": i} for i, link in enumerate(record.links)],
                )
            if facts:
                await conn.execute(
                    insert(f), [{"note_id": note_id, "day": x.day, "text": x.text, "source": x.source} for x in facts]
                )

    async def delete_note(self, path: str) -> None:
        n = self.t.notes
        async with self.engine.begin() as conn:
            await conn.execute(delete(n).where(n.c.path == path))

    async def upsert_summary(self, record: SummaryRecord) -> None:
        s = self.t.summaries
        stmt = pg_insert(s).values(
            period=record.period,
            key=record.key,
            path=record.path,
            text=record.text,
            links=record.links,
            body_hash=record.body_hash,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[s.c.period, s.c.key],
            set_={
                "path": stmt.excluded.path,
                "text": stmt.excluded.text,
                "links": stmt.excluded.links,
                "body_hash": stmt.excluded.body_hash,
                "embedding": None,
                "embedding_model": None,
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def get(self, name: str) -> NoteRecord | None:
        n = self.t.notes
        rows = await self._notes(select(n).where(n.c.name == name.lower()))
        return rows[0] if rows else None

    async def by_alias(self, alias: str) -> list[NoteRecord]:
        n = self.t.notes
        return await self._notes(select(n).where(alias.lower() == any_(n.c.aliases)).order_by(n.c.name))

    async def fuzzy(self, text_: str, limit: int = 3) -> list[tuple[NoteRecord, float]]:
        """pg_trgm's similarity on the name and every alias; kept as SQL because `%` and unnest read best as SQL."""
        sql = text(
            f"""SELECT id, name, path, type, aliases, summary, body_hash, updated_at,
                       GREATEST(similarity(name, :q),
                                COALESCE((SELECT max(similarity(a, :q)) FROM unnest(aliases) a), 0)) AS score
                FROM "{self.s}".notes
                WHERE name % :q OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE a % :q)
                ORDER BY score DESC, name LIMIT :limit"""
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(sql, {"q": text_.lower(), "limit": limit})).mappings().all()
            links = await self._links_for(conn, [r["id"] for r in rows])
            return [(_note(r, links.get(r["id"])), float(r["score"])) for r in rows]

    async def backlinks(self, name: str) -> list[NoteRecord]:
        n, links = self.t.notes, self.t.links
        stmt = (
            select(n).select_from(links.join(n, n.c.id == links.c.from_note)).where(links.c.to_name == name.lower())
        ).order_by(n.c.name)
        return await self._notes(stmt)

    async def facts(
        self, name: str | None = None, day: date | None = None, since: date | None = None
    ) -> list[FactRecord]:
        n, f = self.t.notes, self.t.facts
        stmt = select(n.c.name.label("note"), f.c.day, f.c.text, f.c.source).select_from(
            f.join(n, n.c.id == f.c.note_id)
        )
        if name is not None:
            stmt = stmt.where(n.c.name == name.lower())
        if day is not None:
            stmt = stmt.where(f.c.day == day)
        if since is not None:
            stmt = stmt.where(f.c.day >= since)
        stmt = stmt.order_by(f.c.day.desc(), f.c.id)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [FactRecord(note=r["note"], day=r["day"], text=r["text"], source=r["source"]) for r in rows]

    async def summary(self, period: str, key: str) -> SummaryRecord | None:
        s = self.t.summaries
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(s).where(s.c.period == period, s.c.key == key))).mappings().first()
        return _summary(row) if row is not None else None

    async def summaries_in(self, period: str, keys: list[str]) -> list[SummaryRecord]:
        """Several keys in one query, in the order asked."""
        if not keys:
            return []
        s = self.t.summaries
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(s).where(s.c.period == period, s.c.key.in_(keys)))).mappings().all()
        by_key = {r["key"]: _summary(r) for r in rows}
        return [by_key[k] for k in keys if k in by_key]

    async def vocabulary(self) -> list[tuple[str, str]]:
        n = self.t.notes
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(n.c.name, n.c.aliases).order_by(n.c.name))).all()
        out: list[tuple[str, str]] = []
        for name, aliases in rows:
            out.append((name, name))
            out.extend((a, name) for a in (aliases or []) if a != name)
        return out

    # ---- embeddings ---------------------------------------------------------------------------

    async def stale_embeddings(self, model: str, limit: int = 200) -> list[EmbedTarget]:
        n, s = self.t.notes, self.t.summaries
        stale_n = (
            select(n).where(or_(n.c.embedding.is_(None), n.c.embedding_model.is_distinct_from(model))).limit(limit)
        )
        stale_s = (
            select(s).where(or_(s.c.embedding.is_(None), s.c.embedding_model.is_distinct_from(model))).limit(limit)
        )
        out: list[EmbedTarget] = []
        async with self.engine.connect() as conn:
            for r in (await conn.execute(stale_n)).mappings().all():
                out.append(EmbedTarget(path=r["path"], text=embedding_text(_note(r))))
            for r in (await conn.execute(stale_s)).mappings().all():
                out.append(EmbedTarget(path=r["path"], text=embedding_text(_summary(r))))
        return out[:limit]

    async def set_embedding(self, path: str, vector: list[float], model: str) -> None:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"{len(vector)} dimensions; the index is built for {EMBEDDING_DIMENSIONS}")
        n, s = self.t.notes, self.t.summaries
        async with self.engine.begin() as conn:
            r = await conn.execute(update(n).where(n.c.path == path).values(embedding=vector, embedding_model=model))
            if r.rowcount == 0:
                await conn.execute(update(s).where(s.c.path == path).values(embedding=vector, embedding_model=model))

    async def nearest(self, vector: list[float], limit: int = 8) -> list[Neighbour]:
        """Cosine similarity through pgvector's <=> operator (the HNSW index is built for it)."""
        n, s = self.t.notes, self.t.summaries
        q = bindparam("q", vector, type_=Vector(EMBEDDING_DIMENSIONS))
        score_n = (literal_column("1") - n.c.embedding.op("<=>")(q)).label("score")
        score_s = (literal_column("1") - s.c.embedding.op("<=>")(q)).label("score")
        notes_q = select(n, score_n).where(n.c.embedding.is_not(None)).order_by(n.c.embedding.op("<=>")(q)).limit(limit)
        sums_q = select(s, score_s).where(s.c.embedding.is_not(None)).order_by(s.c.embedding.op("<=>")(q)).limit(limit)
        out: list[Neighbour] = []
        async with self.engine.connect() as conn:
            rows = (await conn.execute(notes_q)).mappings().all()
            links = await self._links_for(conn, [r["id"] for r in rows])
            for r in rows:
                out.append(Neighbour(record=_note(r, links.get(r["id"])), score=round(float(r["score"]), 4)))
            for r in (await conn.execute(sums_q)).mappings().all():
                out.append(Neighbour(record=_summary(r), score=round(float(r["score"]), 4)))
        out.sort(key=lambda x: (-x.score, x.record.path))
        return out[:limit]

    # ---- the decide step ------------------------------------------------------------------------

    async def by_path(self, path: str) -> NoteRecord | None:
        n = self.t.notes
        rows = await self._notes(select(n).where(n.c.path == path))
        return rows[0] if rows else None

    async def summary_by_path(self, path: str) -> SummaryRecord | None:
        s = self.t.summaries
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(s).where(s.c.path == path))).mappings().first()
        return _summary(row) if row is not None else None

    async def catalogue(self, since: date | None = None) -> list[NoteRecord | SummaryRecord]:
        n, s = self.t.notes, self.t.summaries
        notes = await self._notes(select(n).order_by(n.c.path))
        cond = s.c.period != "day"
        if since is not None:
            cond = or_(cond, s.c.key >= since.isoformat())
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(s).where(cond).order_by(s.c.path))).mappings().all()
        return [*notes, *(_summary(r) for r in rows)]


def _summary(row: Any) -> SummaryRecord:
    return SummaryRecord(
        period=row["period"],
        key=row["key"],
        path=row["path"],
        text=row["text"],
        links=list(row["links"] or []),
        body_hash=row["body_hash"],
    )
