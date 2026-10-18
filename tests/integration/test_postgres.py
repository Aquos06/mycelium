"""Real Postgres: schema, registry and tracer recording."""

import asyncio
import uuid
from pathlib import Path

import pytest

from mycelium_sdk import validate_manifest
from tests.conftest import DATABASE_URL, NATS_URL, needs_nats, needs_pg

pytestmark = [pytest.mark.integration, needs_pg]

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
async def pool():
    import asyncpg

    p = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    # apply schema (idempotent) so the tests also work against a bare CI Postgres
    await p.execute((REPO / "db/init.sql").read_text())
    yield p
    await p.close()


async def test_schema_has_core_tables(pool):
    rows = await pool.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
        "AND table_name IN ('events','modules','traces')"
    )
    assert {r["table_name"] for r in rows} == {"events", "modules", "traces"}
    ext = await pool.fetch("SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm')")
    assert {r["extname"] for r in ext} == {"vector", "pg_trgm"}


async def test_registry_upsert_and_status(pool):
    from supervisor.registry import PostgresRegistry

    reg = PostgresRegistry(DATABASE_URL)
    reg.pool = pool
    name = f"itest-{uuid.uuid4().hex[:6]}"
    m = validate_manifest({"name": name, "purpose": "Integration test module."})
    await reg.upsert(m, "building", None)
    await reg.upsert(m, "running", "img:1")
    await reg.set_status(name, "stopped")
    row = next(r for r in await reg.all() if r["name"] == name)
    assert row["status"] == "stopped" and row["image"] == "img:1" and row["manifest"]["name"] == name
    await pool.execute("DELETE FROM modules WHERE name=$1", name)


@needs_nats
async def test_tracer_records_bus_traffic(pool):
    import nats

    from tracer import Recorder

    marker = uuid.uuid4().hex
    nc = await nats.connect(NATS_URL)
    try:
        await Recorder(pool).attach(nc)
        await nc.flush()
        await nc.publish(f"mod.itest.{marker}", b'{"hello": "world"}')
        await nc.publish(f"_INBOX.{marker}", b"{}")
        await nc.flush()
        for _ in range(30):
            rows = await pool.fetch("SELECT subject, source, payload FROM events WHERE subject LIKE $1", f"%{marker}%")
            if rows:
                break
            await asyncio.sleep(0.1)
        assert [r["subject"] for r in rows] == [f"mod.itest.{marker}"]
        assert rows[0]["source"] == "itest"
    finally:
        await nc.drain()
