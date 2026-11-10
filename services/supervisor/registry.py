"""Module registry: what is deployed, which manifest, which status. Postgres in prod, memory in tests."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from mycelium_sdk import Manifest
from mycelium_sdk.db import CORE_MIGRATIONS, make_engine, migrate
from mycelium_sdk.db.core import modules

from .schemas import ModuleRecord, ModuleStatus


class Registry(Protocol):
    async def upsert(self, manifest: Manifest, status: ModuleStatus, image: str | None) -> None: ...
    async def set_status(self, name: str, status: ModuleStatus) -> None: ...
    async def remove(self, name: str) -> bool: ...
    async def all(self) -> list[ModuleRecord]: ...


class MemoryRegistry:
    def __init__(self) -> None:
        self.rows: dict[str, ModuleRecord] = {}

    async def upsert(self, manifest: Manifest, status: ModuleStatus, image: str | None) -> None:
        self.rows[manifest.name] = ModuleRecord(
            name=manifest.name,
            version=manifest.version,
            status=status,
            image=image,
            manifest=manifest.model_dump(),
        )

    async def set_status(self, name: str, status: ModuleStatus) -> None:
        if name in self.rows:
            self.rows[name].status = status

    async def remove(self, name: str) -> bool:
        return self.rows.pop(name, None) is not None

    async def all(self) -> list[ModuleRecord]:
        return list(self.rows.values())


class PostgresRegistry:
    """The `modules` table (mycelium_sdk.db.core). connect() also runs the core migrations: the supervisor owns it."""

    def __init__(self, dsn: str, engine: AsyncEngine | None = None) -> None:
        self.dsn = dsn
        self.engine = engine

    async def connect(self) -> None:
        if self.engine is None:
            self.engine = make_engine(self.dsn)
        await migrate(self.engine, CORE_MIGRATIONS)

    async def upsert(self, manifest: Manifest, status: ModuleStatus, image: str | None) -> None:
        stmt = pg_insert(modules).values(
            name=manifest.name,
            version=manifest.version,
            status=status,
            image=image,
            manifest=manifest.model_dump(),
            updated_at=func.now(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[modules.c.name],
            set_={
                "version": stmt.excluded.version,
                "status": stmt.excluded.status,
                "image": stmt.excluded.image,
                "manifest": stmt.excluded.manifest,
                "updated_at": func.now(),
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def set_status(self, name: str, status: ModuleStatus) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                update(modules).where(modules.c.name == name).values(status=status, updated_at=func.now())
            )

    async def remove(self, name: str) -> bool:
        """The module's row, gone: it is no longer listed, and reconcile never brings it back."""
        async with self.engine.begin() as conn:
            return (await conn.execute(delete(modules).where(modules.c.name == name))).rowcount > 0

    async def all(self) -> list[ModuleRecord]:
        stmt = select(
            modules.c.name, modules.c.version, modules.c.status, modules.c.image, modules.c.manifest
        ).order_by(modules.c.name)
        async with self.engine.connect() as conn:
            return [ModuleRecord.model_validate(dict(r)) for r in (await conn.execute(stmt)).mappings().all()]
