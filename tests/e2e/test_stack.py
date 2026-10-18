"""End to end against the running docker compose stack:
supervisor builds + starts the hello container, events flow, tracer records them.

    docker compose up -d --build
    NATS_URL=nats://localhost:4222 DATABASE_URL=postgresql://mycelium:mycelium@localhost:5432/mycelium \
      pytest -m e2e tests/e2e
"""

import asyncio
import uuid

import pytest

from mycelium_sdk import NatsBus
from tests.conftest import DATABASE_URL, NATS_URL, needs_nats, needs_pg

pytestmark = [pytest.mark.e2e, needs_nats, needs_pg]


async def wait_for(fn, timeout=60, interval=1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        try:
            last = await fn()
            if last:
                return last
        except Exception as e:  # noqa: BLE001
            last = e
        await asyncio.sleep(interval)
    raise AssertionError(f"timed out; last={last!r}")


@pytest.fixture
async def bus():
    b = NatsBus(NATS_URL, name="e2e")
    await b.connect()
    yield b
    await b.close()


async def test_supervisor_is_up(bus):
    reply = await wait_for(lambda: bus.request("rpc.sys.list", {}, timeout=5), timeout=120)
    assert reply["ok"] is True


async def test_deploy_hello_and_talk_to_it(bus):
    import asyncpg

    deployed = await bus.request("rpc.sys.deploy", {"name": "hello"}, timeout=600)
    assert deployed["ok"] is True, deployed

    async def healthy():
        r = await bus.request("rpc.mod.hello.health", {}, timeout=2)
        return r if r.get("ok") else None

    await wait_for(healthy, timeout=90)

    marker = uuid.uuid4().hex[:8]
    before = (await bus.request("rpc.mod.hello.stats", {}))["count"]
    await bus.publish("sense.chat", {"text": f"e2e {marker}"})

    async def counted():
        r = await bus.request("rpc.mod.hello.stats", {}, timeout=2)
        return r if r["count"] == before + 1 else None

    await wait_for(counted, timeout=30)

    # tracer recorded the module's event and the chat input
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1)
    try:

        async def recorded():
            rows = await pool.fetch(
                "SELECT subject FROM events WHERE ts > now() - interval '5 minutes' "
                "AND (subject = 'mod.hello.message.counted' OR payload->>'text' = $1)",
                f"e2e {marker}",
            )
            subjects = {r["subject"] for r in rows}
            return subjects if {"sense.chat", "mod.hello.message.counted"} <= subjects else None

        await wait_for(recorded, timeout=30)
        row = await pool.fetchrow("SELECT status FROM modules WHERE name='hello'")
        assert row["status"] == "running"
    finally:
        await pool.close()

    health = await bus.request("rpc.sys.health", {}, timeout=10)
    assert health["modules"]["hello"]["ok"] is True

    logs = await bus.request("rpc.sys.logs", {"name": "hello", "tail": 20}, timeout=10)
    assert logs["ok"] is True


async def test_bad_deploy_is_rejected(bus):
    reply = await bus.request("rpc.sys.deploy", {"name": "../../etc"}, timeout=10)
    assert reply["ok"] is False


async def test_stop_hello(bus):
    reply = await bus.request("rpc.sys.stop", {"name": "hello"}, timeout=60)
    assert reply["ok"] is True
