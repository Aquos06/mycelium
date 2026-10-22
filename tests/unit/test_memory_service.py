"""The memory service on the bus: rpc.memory.remember / lookup / recall / reindex, and module notes on deploy."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from memory.index import InMemoryIndex
from memory.service import MemoryService
from memory.vault import Vault
from mycelium_sdk import InMemoryBus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "vault"
TODAY = date(2026, 10, 21)


@pytest.fixture
async def svc(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "vault")
    bus = InMemoryBus()
    service = MemoryService(bus, Vault(tmp_path / "vault"), InMemoryIndex(), today=lambda: TODAY)
    await service.start()
    return service


async def test_start_indexes_the_vault(svc):
    reply = await svc.bus.request("rpc.memory.lookup", {"name": "小美"})
    assert reply["ok"] and reply["matches"][0] == {
        "name": "mei",
        "path": "people/mei.md",
        "type": "person",
        "via": "alias",
        "score": 1.0,
    }


async def test_remember_appends_fact_to_existing_note(svc):
    reply = await svc.bus.request(
        "rpc.memory.remember",
        {
            "note": "mei",
            "fact": {"day": "2026-10-20", "text": "wants to try [[ramen-place-xinyi]] again"},
            "source": "ev:50001",
        },
    )
    assert reply == {"ok": True, "path": "people/mei.md", "created": False}
    text = (svc.vault.root / "people/mei.md").read_text()
    assert "- 2026-10-20 wants to try [[ramen-place-xinyi]] again  (ev:50001)" in text
    assert text.index("2026-10-20") < text.index("2026-10-14")  # newest first
    facts = await svc.index.facts(name="mei")
    assert facts[0].day == date(2026, 10, 20) and facts[0].source == "ev:50001"


async def test_remember_creates_note_with_type_aliases_and_summary(svc):
    reply = await svc.bus.request(
        "rpc.memory.remember",
        {
            "note": "tainan",
            "type": "place",
            "aliases": ["台南"],
            "summary": "City in the south. [[mei]] is moving there in December.",
            "fact": {"text": "Mei is moving there in December"},  # no day -> today
            "source": "hansen",
        },
    )
    assert reply == {"ok": True, "path": "places/tainan.md", "created": True}
    note = svc.vault.read("places/tainan.md")
    assert note.type == "place" and note.aliases == ["台南"] and note.links == ["mei"]
    assert note.facts[0].day == TODAY and note.facts[0].source == "hansen"
    assert (await svc.index.by_alias("台南"))[0].name == "tainan"
    assert {r.name for r in await svc.index.backlinks("mei")} >= {"tainan", "ramen-place-xinyi"}


async def test_remember_without_fact_or_summary_is_rejected(svc):
    reply = await svc.bus.request("rpc.memory.remember", {"note": "ghost"})
    assert reply["ok"] is False and "fact" in reply["error"]


async def test_remember_rejects_bad_names(svc):
    reply = await svc.bus.request("rpc.memory.remember", {"note": "../etc", "fact": {"text": "x"}})
    assert reply["ok"] is False


async def test_recall_over_the_bus(svc):
    reply = await svc.bus.request("rpc.memory.recall", {"query": "who did I have dinner with last Wednesday?"})
    assert reply["ok"] and reply["items"][0]["note"] == "summaries/2026/10/14.md"
    assert reply["budget"]["max"] == 8  # default


async def test_reindex_over_the_bus(svc):
    (svc.vault.root / "things").mkdir()
    (svc.vault.root / "things/bike.md").write_text("Grey gravel bike.\n")
    reply = await svc.bus.request("rpc.memory.reindex", {})
    assert reply == {"ok": True, "notes": 1, "summaries": 0, "skipped": 7}
    assert (await svc.index.get("bike")).type == "thing"


async def test_module_deployed_writes_a_module_note(svc):
    async def fake_list(msg):
        await msg.respond(
            {
                "ok": True,
                "modules": [
                    {
                        "name": "reminders",
                        "status": "running",
                        "manifest": {
                            "name": "reminders",
                            "version": "0.2.0",
                            "purpose": "Keeps reminders and fires them on time.",
                            "requests": ["add", "list"],
                        },
                    }
                ],
            }
        )

    await svc.bus.subscribe("rpc.sys.list", fake_list)
    await svc.bus.publish("sys.module.deployed", {"name": "reminders", "version": "0.2.0", "image": "img"})

    note = svc.vault.read("modules/reminders.md")
    assert note.type == "module"
    assert note.summary.startswith("Keeps reminders and fires them on time.")
    assert "rpc.mod.reminders.add" in note.summary and "rpc.mod.reminders.list" in note.summary
    assert note.facts[0].text == "deployed v0.2.0" and note.facts[0].source == "sys" and note.facts[0].day == TODAY
    assert (await svc.index.get("reminders")).type == "module"


async def test_module_redeploy_appends_not_duplicates(svc):
    async def fake_list(msg):
        await msg.respond(
            {
                "ok": True,
                "modules": [
                    {
                        "name": "expenses",
                        "manifest": {
                            "name": "expenses",
                            "version": "0.2.0",
                            "purpose": "Tracks spending from chat.",
                            "requests": ["summary"],
                        },
                    }
                ],
            }
        )

    await svc.bus.subscribe("rpc.sys.list", fake_list)
    await svc.bus.publish("sys.module.deployed", {"name": "expenses", "version": "0.2.0", "image": "img"})
    note = svc.vault.read("modules/expenses.md")
    assert note.aliases == ["spending", "支出"]  # hand-written aliases survive a redeploy
    assert [f.text for f in note.facts] == ["deployed v0.2.0", "deployed v0.1.0"]
