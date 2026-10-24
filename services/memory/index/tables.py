"""The index tables as SQLAlchemy Core Table objects, bound to one schema per PostgresIndex.

`IndexTables("memory").metadata` is what Alembic autogenerates the migrations from; at runtime a
PostgresIndex builds its own copy for its schema and every statement comes from these objects.
"""

from __future__ import annotations

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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import UserDefinedType

CANONICAL_SCHEMA = "memory"  # what the migrations name; mapped to the real schema with schema_translate_map


class Vector(UserDefinedType):
    """pgvector's VECTOR(n); filled in M4, declared now so the tables match the migration."""

    cache_ok = True

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        return f"VECTOR({self.dim})"


class IndexTables:
    def __init__(self, schema: str = CANONICAL_SCHEMA) -> None:
        self.schema = schema
        self.metadata = MetaData(schema=schema)
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
            Column("embedding", Vector(1024)),  # of name + summary; NULL until computed (M4)
            Index("notes_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
            Index("notes_aliases_idx", "aliases", postgresql_using="gin"),
        )
        self.links = Table(
            "links",
            self.metadata,
            Column("from_note", BigInteger, ForeignKey(f"{schema}.notes.id", ondelete="CASCADE"), primary_key=True),
            Column("to_name", Text, primary_key=True),  # by name: the target note may not exist yet
            Column("ord", Integer, nullable=False, server_default=text("0")),  # order of first appearance
            Index("links_to_name_idx", "to_name"),
        )
        self.facts = Table(
            "facts",
            self.metadata,
            Column("id", BigInteger, primary_key=True),
            Column("note_id", BigInteger, ForeignKey(f"{schema}.notes.id", ondelete="CASCADE"), nullable=False),
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
            Column("embedding", Vector(1024)),
        )
