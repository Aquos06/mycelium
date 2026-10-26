"""The index tables as SQLAlchemy Core Table objects, bound to one schema per PostgresIndex.

`IndexTables(None).metadata` is what Alembic autogenerates the migrations from (the schema comes from the
connection's search_path at run time); a PostgresIndex builds its own copy for its schema and every
statement comes from these objects.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    cast,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import UserDefinedType

CANONICAL_SCHEMA = "memory"  # what the migrations name; mapped to the real schema with schema_translate_map
EMBEDDING_DIMENSIONS = 1024  # one size for the whole index; the gateway's embed slot pins the same number


class Vector(UserDefinedType):
    """pgvector's VECTOR(n). asyncpg has no vector codec and falls back to text for it, so values travel as
    '[0.1,0.2,...]' inside CAST(... AS VECTOR(n)) and come back as text to be parsed."""

    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIMENSIONS) -> None:
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        return f"VECTOR({self.dim})"

    def bind_processor(self, dialect: Any):
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(f"{float(x):.8g}" for x in value) + "]"

        return process

    def bind_expression(self, bindvalue: Any) -> Any:
        return cast(bindvalue, self)

    def result_processor(self, dialect: Any, coltype: Any):
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, str):
                return [float(x) for x in value.strip("[]").split(",") if x]
            return [float(x) for x in value]

        return process


class IndexTables:
    """The tables bound to one schema; schema=None is what Alembic autogenerates from (migrations/env.py)."""

    def __init__(self, schema: str | None = CANONICAL_SCHEMA) -> None:
        self.schema = schema
        self.metadata = MetaData(schema=schema)
        notes_id = f"{schema}.notes.id" if schema else "notes.id"
        self.notes = Table(
            "notes",
            self.metadata,
            Column("id", BigInteger, primary_key=True),
            Column("path", Text, nullable=False, unique=True),  # people/mei.md
            Column("name", Text, nullable=False, unique=True),  # mei: the [[link]] target
            Column("type", Text, nullable=False),
            Column("aliases", ARRAY(Text), nullable=False, server_default=text("'{}'")),  # lowercased
            Column("summary", Text, nullable=False, server_default=text("''")),  # first paragraph
            Column("body_hash", Text, nullable=False),  # skip unchanged files on re-index
            Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
            Column("embedding", Vector(EMBEDDING_DIMENSIONS)),  # of name + aliases + summary; NULL until computed
            Column("embedding_model", Text),  # which model made it; another model means re-embed
            Index("notes_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
            Index("notes_aliases_idx", "aliases", postgresql_using="gin"),
            Index(
                "notes_embedding_hnsw",
                "embedding",
                postgresql_using="hnsw",
                postgresql_with={"m": 16, "ef_construction": 64},
                postgresql_ops={"embedding": "vector_cosine_ops"},
            ),
        )
        self.links = Table(
            "links",
            self.metadata,
            Column("from_note", BigInteger, ForeignKey(notes_id, ondelete="CASCADE"), primary_key=True),
            Column("to_name", Text, primary_key=True),  # by name: the target note may not exist yet
            Column("ord", Integer, nullable=False, server_default=text("0")),  # order of first appearance
            Index("links_to_name_idx", "to_name"),
        )
        self.facts = Table(
            "facts",
            self.metadata,
            Column("id", BigInteger, primary_key=True),
            Column("note_id", BigInteger, ForeignKey(notes_id, ondelete="CASCADE"), nullable=False),
            Column("day", Date, nullable=False),
            Column("text", Text, nullable=False),
            Column("source", Text),  # 'ev:48213' | 'hansen' | 'consolidation' | 'sys'
            Index("facts_day_idx", "day"),
            Index("facts_note_idx", "note_id"),
        )
        self.summaries = Table(
            "summaries",
            self.metadata,
            Column("period", Text, primary_key=True),  # day | week | month
            Column("key", Text, primary_key=True),  # 2026-10-14 | 2026-W42 | 2026-10
            Column("path", Text, nullable=False),
            Column("text", Text, nullable=False),
            Column("links", ARRAY(Text), nullable=False, server_default=text("'{}'")),
            Column("body_hash", Text, nullable=False),
            Column("embedding", Vector(EMBEDDING_DIMENSIONS)),
            Column("embedding_model", Text),
            Index(
                "summaries_embedding_hnsw",
                "embedding",
                postgresql_using="hnsw",
                postgresql_with={"m": 16, "ef_construction": 64},
                postgresql_ops={"embedding": "vector_cosine_ops"},
            ),
        )
