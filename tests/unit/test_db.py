"""The database layer without a database: URL mapping, the core tables, both Alembic trees, statement shapes."""

import re

from alembic.script import ScriptDirectory
from sqlalchemy import any_, select
from sqlalchemy.dialects import postgresql

from memory.index import MIGRATIONS as MEMORY_MIGRATIONS
from memory.index.tables import IndexTables
from mycelium_sdk.db import CORE_MIGRATIONS, alembic_config, head, sqlalchemy_url
from mycelium_sdk.db.core import events, metadata, modules, traces


def test_sqlalchemy_url_uses_the_asyncpg_driver():
    assert sqlalchemy_url("postgresql://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"
    assert sqlalchemy_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert sqlalchemy_url("postgresql+asyncpg://u@h/db") == "postgresql+asyncpg://u@h/db"


def test_core_tables_match_the_migration():
    assert set(metadata.tables) == {"events", "modules", "traces"}
    assert {c.name for c in events.c} == {"id", "ts", "subject", "source", "is_request", "payload"}
    assert modules.c.name.primary_key and traces.c.feedback.nullable


def test_both_migration_trees_load_and_have_one_head():
    for tree in (CORE_MIGRATIONS, MEMORY_MIGRATIONS):
        scripts = ScriptDirectory.from_config(alembic_config(tree, schema="memtest_x"))
        assert re.fullmatch(r"\d{14}", scripts.get_current_head()) and head(tree) == scripts.get_current_head()
        assert (tree / "env.py").is_file() and (tree / "alembic.ini").is_file()


def test_memory_tables_are_bound_to_their_schema():
    t = IndexTables("memtest_x")
    assert t.notes.schema == "memtest_x" and t.facts.c.note_id.references(t.notes.c.id)
    sql = str(select(t.notes.c.name).where(any_(t.notes.c.aliases) == "小美").compile(dialect=postgresql.dialect()))
    assert "memtest_x.notes" in sql and "ANY (memtest_x.notes.aliases)" in sql
    assert str(t.notes.c.embedding.type.get_col_spec()) == "VECTOR(1024)"
