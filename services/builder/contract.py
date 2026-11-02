"""tests/test_contract.py: the builder's own test, next to the coder's, rewritten after every round.

A coder grades its own work with the tests it writes; this one it cannot edit. It reads the manifest when it
runs, so it is the same file for every module: the module starts with what it declared, answers health, gives
every declared request a reply (ok true, or ok false with an error) instead of hanging or crashing, and keeps
running after a message on every subject it listens to that is not meant for it.
"""

CONTRACT_TEST = '''"""Written by the builder on every round from the manifest; edits here are replaced."""

from pathlib import Path

import pytest

from app.main import build
from mycelium_sdk import InMemoryBus, load_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_manifest(ROOT / "manifest.yaml")


@pytest.fixture
async def running(tmp_path):
    bus = InMemoryBus()
    mod = build(manifest_path=ROOT / "manifest.yaml", bus=bus, data_dir=tmp_path)
    await mod.start()
    yield bus
    await mod.stop()


async def test_contract_answers_health(running):
    reply = await running.request(f"rpc.mod.{MANIFEST.name}.health", {}, timeout=5)
    assert reply["ok"] is True


@pytest.mark.parametrize("action", MANIFEST.requests or ["health"])
async def test_contract_every_request_answers(running, action):
    reply = await running.request(f"rpc.mod.{MANIFEST.name}.{action}", {}, timeout=5)
    assert isinstance(reply.get("ok"), bool), reply


@pytest.mark.parametrize("subject", MANIFEST.subscribes or ["sense.chat"])
async def test_contract_survives_a_message_not_for_it(running, subject):
    concrete = subject.replace(">", "x").replace("*", "x")
    await running.publish(concrete, {"id": "contract", "hops": 0, "text": "the weather is nice today"})
    reply = await running.request(f"rpc.mod.{MANIFEST.name}.health", {}, timeout=5)
    assert reply["ok"] is True
'''
