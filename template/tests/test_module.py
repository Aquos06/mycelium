from pathlib import Path

import pytest

from app.main import build
from mycelium_sdk import InMemoryBus, load_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_is_valid():
    load_manifest(ROOT / "manifest.yaml")


@pytest.mark.asyncio
async def test_health(tmp_path):
    bus = InMemoryBus()
    mod = build(manifest_path=ROOT / "manifest.yaml", bus=bus, data_dir=tmp_path)
    await mod.start()
    reply = await bus.request(f"rpc.mod.{mod.name}.health", {})
    assert reply["ok"] is True
    await mod.stop()
