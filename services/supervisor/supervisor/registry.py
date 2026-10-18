"""Module registry: what is deployed, which manifest, which status. Postgres in prod, memory in tests."""

from __future__ import annotations

import json
from typing import Any, Protocol

from mycelium_sdk import Manifest


class Registry(Protocol):
    async def upsert(self, manifest: Manifest, status: str, image: str | None) -> None: ...
    async def set_status(self, name: str, status: str) -> None: ...
    async def all(self) -> list[dict[str, Any]]: ...


class MemoryRegistry:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def upsert(self, manifest: Manifest, status: str, image: str | None) -> None:
        self.rows[manifest.name] = {
            "name": manifest.name,
            "version": manifest.version,
            "status": status,
            "image": image,
            "manifest": manifest.model_dump(),
        }

    async def set_status(self, name: str, status: str) -> None:
        if name in self.rows:
            self.rows[name]["status"] = status

    async def all(self) -> list[dict[str, Any]]:
        return list(self.rows.values())


class PostgresRegistry:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool = None

    async def connect(self) -> None:
        import asyncpg

        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=4)

    async def upsert(self, manifest: Manifest, status: str, image: str | None) -> None:
        await self.pool.execute(
            """
            INSERT INTO modules (name, version, status, image, manifest, updated_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, now())
            ON CONFLICT (name) DO UPDATE
              SET version = EXCLUDED.version, status = EXCLUDED.status,
                  image = EXCLUDED.image, manifest = EXCLUDED.manifest, updated_at = now()
            """,
            manifest.name,
            manifest.version,
            status,
            image,
            json.dumps(manifest.model_dump()),
        )

    async def set_status(self, name: str, status: str) -> None:
        await self.pool.execute("UPDATE modules SET status=$2, updated_at=now() WHERE name=$1", name, status)

    async def all(self) -> list[dict[str, Any]]:
        rows = await self.pool.fetch("SELECT name, version, status, image, manifest FROM modules ORDER BY name")
        return [{**dict(r), "manifest": json.loads(r["manifest"])} for r in rows]
