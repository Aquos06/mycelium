#!/usr/bin/env python3
"""Run every owner's Alembic tree to head against one database (`make migrate`).

    DATABASE_URL=postgresql://... python scripts/migrate.py
    python scripts/migrate.py            # local compose Postgres: POSTGRES_PASSWORD / PG_PORT from the environment

Services do the same for their own tree at start; this is for a fresh database before the stack is
up, for CI, or after pulling a change.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services"))

from memory.index import MIGRATIONS as MEMORY_MIGRATIONS  # noqa: E402
from mycelium_sdk.db import CORE_MIGRATIONS, make_engine, migrate  # noqa: E402


def database_url() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url
    password = os.environ.get("POSTGRES_PASSWORD", "mycelium")
    port = os.environ.get("PG_PORT", "5432")
    return f"postgresql://mycelium:{password}@localhost:{port}/mycelium"


async def main() -> int:
    engine = make_engine(database_url(), pool_size=1)
    try:
        print("core:", await migrate(engine, CORE_MIGRATIONS))
        schema = os.environ.get("MEMORY_SCHEMA", "memory")
        print(f"memory ({schema}):", await migrate(engine, MEMORY_MIGRATIONS, schema=schema))
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
