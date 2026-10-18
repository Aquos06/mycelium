from pathlib import Path

import pytest

from app.main import build, today
from mycelium_sdk import InMemoryBus, load_manifest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
async def running(tmp_path):
    bus = InMemoryBus()
    mod = build(manifest_path=ROOT / "manifest.yaml", bus=bus, data_dir=tmp_path)
    await mod.start()
    yield bus, mod
    await mod.stop()


def test_manifest_is_valid():
    m = load_manifest(ROOT / "manifest.yaml")
    assert m.name == "hello"


@pytest.mark.asyncio
async def test_counts_chat_and_emits(running):
    bus, _ = running
    await bus.publish("sense.chat", {"text": "hi"})
    await bus.publish("sense.chat", {"text": "again"})
    counted = bus.events("mod.hello.message.counted")
    assert [d["count"] for _, d in counted] == [1, 2]


@pytest.mark.asyncio
async def test_stats_today(running):
    bus, _ = running
    await bus.publish("sense.chat", {"text": "hi"})
    reply = await bus.request("rpc.mod.hello.stats", {})
    assert reply == {"ok": True, "day": today(), "count": 1, "total": 1}


@pytest.mark.asyncio
async def test_stats_bad_day(running):
    bus, _ = running
    reply = await bus.request("rpc.mod.hello.stats", {"day": "not-a-date"})
    assert reply["ok"] is False
    assert "YYYY-MM-DD" in reply["error"]


@pytest.mark.asyncio
async def test_milestone_observed(running):
    bus, _ = running
    for _ in range(10):
        await bus.publish("sense.chat", {"text": "x"})
    obs = [d for _, d in bus.events("brain.observe") if d["type"] == "milestone"]
    assert len(obs) == 1 and obs[0]["source"] == "hello"


@pytest.mark.asyncio
async def test_count_persists_across_restart(tmp_path):
    bus = InMemoryBus()
    mod = build(manifest_path=ROOT / "manifest.yaml", bus=bus, data_dir=tmp_path)
    await mod.start()
    await bus.publish("sense.chat", {"text": "hi"})
    await mod.stop()

    bus2 = InMemoryBus()
    mod2 = build(manifest_path=ROOT / "manifest.yaml", bus=bus2, data_dir=tmp_path)
    await mod2.start()
    reply = await bus2.request("rpc.mod.hello.stats", {})
    assert reply["count"] == 1
    await mod2.stop()
