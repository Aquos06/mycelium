"""Postgres through SQLAlchemy's async engine (asyncpg underneath) and Alembic migrations.

    engine = make_engine(settings.database_url)                   # postgresql:// -> postgresql+asyncpg://
    await migrate(engine, CORE_MIGRATIONS)                         # alembic upgrade head, serialised across services
    await migrate(engine, MEMORY_MIGRATIONS, schema="memtest_x")   # an owner whose tables live in their own schema

Each owner has one Alembic tree and runs it at start, so a fresh database comes up by itself and a
schema change is one more file under versions/. Records stay pydantic and statements are SQLAlchemy
Core over the Table objects in core.py (or the owner's own); nothing is ORM-mapped.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from . import core

__all__ = ["CORE_MIGRATIONS", "alembic_config", "core", "head", "make_engine", "migrate", "sqlalchemy_url"]

CORE_MIGRATIONS = Path(__file__).with_name("migrations") / "core"


def sqlalchemy_url(dsn: str) -> str:
    """A plain postgresql:// DSN (what compose and .env carry) as the asyncpg driver URL."""
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+asyncpg://" + dsn[len(prefix) :]
    return dsn


def make_engine(dsn: str, pool_size: int = 4, **kwargs: Any) -> AsyncEngine:
    return create_async_engine(
        sqlalchemy_url(dsn),
        pool_size=pool_size,
        max_overflow=pool_size,
        json_serializer=lambda o: json.dumps(o, default=str),
        **kwargs,
    )


def alembic_config(
    migrations: Path | str, schema: str | None = None, attributes: Mapping[str, Any] | None = None
) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(migrations).resolve()))
    if schema:
        cfg.attributes["schema"] = schema
    for k, v in (attributes or {}).items():
        cfg.attributes[k] = v
    return cfg


def head(migrations: Path | str) -> str | None:
    return ScriptDirectory.from_config(alembic_config(migrations)).get_current_head()


async def migrate(engine: AsyncEngine, migrations: Path | str, *, schema: str | None = None) -> str | None:
    """Upgrade one owner's tree to head on this engine. Safe to call from several services at once."""
    key = zlib.crc32(f"{Path(migrations).resolve()}:{schema or ''}".encode())
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})  # session lock: survives commits
        if schema:
            await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        await conn.commit()  # end the autobegun transaction so Alembic can run its own
        try:
            await conn.run_sync(_upgrade, alembic_config(migrations, schema))
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            await conn.commit()
    return head(migrations)


def _upgrade(connection: Any, cfg: Config) -> None:
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")
