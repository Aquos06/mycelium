"""Real Postgres: the core migrations, the registry and tracer recording, all through the async engine."""

import asyncio
import uuid

import pytest
from sqlalchemy import text

from mycelium_sdk import validate_manifest
from mycelium_sdk.db import CORE_MIGRATIONS, head, make_engine, migrate
from tests.conftest import DATABASE_URL, NATS_URL, needs_nats, needs_pg

pytestmark = [pytest.mark.integration, needs_pg]


@pytest.fixture
async def engine():
    e = make_engine(DATABASE_URL, pool_size=2)
    await migrate(e, CORE_MIGRATIONS)  # idempotent: also adopts a database made by the old init.sql
    yield e
    await e.dispose()


async def test_core_migration_creates_tables_extensions_and_is_idempotent(engine):
    async with engine.connect() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
                    "AND table_name IN ('events','modules','traces','alembic_version')"
                )
            )
        ).scalars()
        assert set(tables) == {"events", "modules", "traces", "alembic_version"}
        ext = (
            await conn.execute(text("SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm')"))
        ).scalars()
        assert set(ext) == {"vector", "pg_trgm"}
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert version == head(CORE_MIGRATIONS)
    assert await migrate(engine, CORE_MIGRATIONS) == version  # a second run is a no-op
    results = await asyncio.gather(*(migrate(engine, CORE_MIGRATIONS) for _ in range(3)))  # services starting together
    assert results == [version] * 3


async def test_registry_upsert_and_status(engine):
    from supervisor.registry import PostgresRegistry

    reg = PostgresRegistry(DATABASE_URL, engine=engine)
    name = f"itest-{uuid.uuid4().hex[:6]}"
    m = validate_manifest({"name": name, "purpose": "Integration test module."})
    try:
        await reg.upsert(m, "building", None)
        await reg.upsert(m, "running", "img:1")
        await reg.set_status(name, "stopped")
        row = next(r for r in await reg.all() if r["name"] == name)
        assert row["status"] == "stopped" and row["image"] == "img:1" and row["manifest"]["name"] == name
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM modules WHERE name = :n"), {"n": name})


@needs_nats
async def test_tracer_records_bus_traffic_and_traces(engine):
    import nats

    from tracer import Recorder

    marker = uuid.uuid4().hex
    nc = await nats.connect(NATS_URL)
    try:
        await Recorder(engine).attach(nc)
        await nc.flush()
        await nc.publish(f"mod.itest.{marker}", b'{"hello": "world"}')
        await nc.publish(f"_INBOX.{marker}", b"{}")
        await nc.publish(f"trace.itest.{marker}", f'{{"cause": "{marker}", "ok": true}}'.encode())
        await nc.flush()
        rows = []
        for _ in range(30):
            async with engine.connect() as conn:
                rows = (
                    (
                        await conn.execute(
                            text("SELECT subject, source, payload FROM events WHERE subject LIKE :p ORDER BY id"),
                            {"p": f"%{marker}%"},
                        )
                    )
                    .mappings()
                    .all()
                )
            if len(rows) >= 2:
                break
            await asyncio.sleep(0.1)
        # a live tracer on the same bus records the same messages: compare as sets
        assert {r["subject"] for r in rows} == {f"mod.itest.{marker}", f"trace.itest.{marker}"}
        assert rows[0]["source"] == "itest" and rows[0]["payload"] == {"hello": "world"}
        async with engine.connect() as conn:
            trace = (
                (await conn.execute(text("SELECT kind, ref, decision FROM traces WHERE ref = :r"), {"r": marker}))
                .mappings()
                .first()
            )
        assert trace["kind"] == f"itest.{marker}" and trace["decision"]["ok"] is True
    finally:
        await nc.drain()
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM events WHERE subject LIKE :p"), {"p": f"%{marker}%"})
            await conn.execute(text("DELETE FROM traces WHERE ref = :r"), {"r": marker})
