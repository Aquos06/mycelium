"""Real NATS: the JetStream KV bucket behind Main's threads and the gateway's usage counter."""

import uuid

import pytest

from mycelium_sdk import NatsBus, NatsKV
from tests.conftest import NATS_URL, needs_nats

pytestmark = [pytest.mark.integration, needs_nats]


@pytest.fixture
async def kv():
    bus = NatsBus(NATS_URL, name="itest-kv")
    await bus.connect()
    bucket = f"itest_{uuid.uuid4().hex[:8]}"
    store = await NatsKV(bus.nc, bucket).open()
    yield store
    await bus.nc.jetstream().delete_key_value(bucket)
    await bus.close()


async def test_kv_round_trip(kv):
    assert await kv.get("thread/cli/1") is None
    assert await kv.keys() == []
    await kv.put("thread/cli/1", {"turns": [{"role": "user", "text": "hi 小美"}]})
    await kv.put("usage/2026-10", {"usd": 0.01, "calls": 1})
    assert await kv.get("thread/cli/1") == {"turns": [{"role": "user", "text": "hi 小美"}]}
    assert await kv.keys("thread/") == ["thread/cli/1"]
    assert await kv.keys() == ["thread/cli/1", "usage/2026-10"]
    await kv.put("thread/cli/1", {"turns": []})  # overwrite
    assert await kv.get("thread/cli/1") == {"turns": []}
    await kv.delete("thread/cli/1")
    await kv.delete("thread/cli/1")  # idempotent
    assert await kv.get("thread/cli/1") is None
    assert await kv.keys() == ["usage/2026-10"]


async def test_reopen_sees_existing_bucket(kv):
    await kv.put("k", {"v": 1})
    again = await NatsKV(kv._nc, kv.bucket).open()
    assert await again.get("k") == {"v": 1}
