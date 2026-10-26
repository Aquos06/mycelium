"""Embeddings: the sweep through the gateway's embed slot, and recall's fallback rung, on the in-memory index.

The gateway is faked with a toy embedding space: four topics, one axis each; a text's vector counts the words
of each topic. Enough for "similar" to mean something without a model.
"""

import math
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from memory.embedder import Embedder
from memory.index import InMemoryIndex
from memory.indexer import index_file, reindex
from memory.recall import recall
from memory.schemas import NoteRecord, SummaryRecord, embedding_text
from memory.service import MemoryService
from memory.vault import Vault
from mycelium_sdk import InMemoryBus, Message

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "vault"
TODAY = date(2026, 10, 21)

TOPICS = [
    {"ramen", "noodle", "noodles", "shoyu", "dinner", "lunch", "eat", "ate", "restaurant", "shop", "food"},
    {"mei", "小美", "friend", "friends", "person", "people", "tainan"},
    {"twd", "spent", "spending", "expenses", "budget", "paid", "cost", "money"},
    {"mycelium", "module", "deploy", "deployed", "nats", "bus", "service", "code", "project", "memory"},
]


def toy_vector(text: str) -> list[float]:
    words = re.findall(r"\w+", text.lower())
    counts = [sum(w in topic for w in words) + 0.01 for topic in TOPICS]
    norm = math.sqrt(sum(c * c for c in counts))
    return [round(c / norm, 6) for c in counts]


class FakeEmbedSlot:
    """rpc.llm.embed as the gateway answers it, over the toy space."""

    def __init__(self, bus: InMemoryBus, model: str = "toy-embed") -> None:
        self.bus = bus
        self.model = model
        self.fail: str | None = None
        self.calls: list[list[str]] = []

    async def start(self) -> None:
        await self.bus.subscribe("rpc.llm.embed", self._embed)

    async def _embed(self, msg: Message) -> None:
        self.calls.append(list(msg.data["texts"]))
        if self.fail:
            await msg.respond({"ok": False, "error": self.fail})
            return
        vectors = [toy_vector(t) for t in msg.data["texts"]]
        await msg.respond(
            {
                "ok": True,
                "vectors": vectors,
                "model": self.model,
                "dimensions": 4,
                "usage": {"input_tokens": 3 * len(vectors), "output_tokens": 0},
                "provider": "fake",
                "cost_usd": 0.0,
            }
        )


@pytest.fixture
async def world(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "vault")
    bus, vault, index = InMemoryBus(), Vault(tmp_path / "vault"), InMemoryIndex()
    await reindex(vault, index)  # 5 notes + 2 summaries
    slot = FakeEmbedSlot(bus)
    await slot.start()
    embedder = Embedder(bus, index, batch=3)
    return bus, vault, index, slot, embedder


def test_embedding_text_is_the_name_aliases_type_and_state():
    mei = NoteRecord(
        name="mei", path="people/mei.md", type="person", aliases=["mei", "小美"], summary="Friend from Tainan."
    )
    assert embedding_text(mei) == "mei (小美), person. Friend from Tainan."
    bare = NoteRecord(name="tainan", path="places/tainan.md", type="place")
    assert embedding_text(bare) == "tainan, place"
    week = SummaryRecord(period="week", key="2026-W42", path="summaries/2026/W42.md", text="A quiet week.")
    assert embedding_text(week) == "week 2026-W42: A quiet week."


async def test_sweep_embeds_every_stale_row_in_batches_and_traces(world):
    bus, vault, index, slot, embedder = world
    report = await embedder.sweep(cause="m1")
    assert report.error is None and report.model == "toy-embed"
    assert report.embedded == 7 and report.batches == 3  # 3 + 3 + 1
    assert slot.calls[0] == ["mycelium"]  # the probe, to learn which model the slot serves
    assert len(slot.calls) == 4 and all(len(c) <= 3 for c in slot.calls[1:])
    trace = bus.events("trace.embed")[0][1]
    assert trace["ok"] and trace["cause"] == "m1" and trace["report"]["embedded"] == 7

    again = await embedder.sweep()
    assert again.embedded == 0 and again.batches == 0 and len(slot.calls) == 4  # nothing stale, no probe either

    nearest = await index.nearest(toy_vector("ramen noodles"), limit=2)
    assert nearest[0].record.path == "places/ramen-place-xinyi.md" and nearest[0].score > 0.9


async def test_changed_rows_and_a_changed_model_are_embedded_again(world):
    bus, vault, index, slot, embedder = world
    await embedder.sweep()
    assert await index.stale_embeddings("toy-embed") == []

    note = vault.read("people/mei.md")
    note.summary = "Friend from Tainan; now lives in Taipei."
    vault.write(note)
    await index_file(vault, index, note.path)
    stale = await index.stale_embeddings("toy-embed")
    assert [t.path for t in stale] == ["people/mei.md"] and "Taipei" in stale[0].text
    assert (await embedder.sweep()).embedded == 1

    slot.model = "toy-embed-v2"  # the slot now serves another model: every vector is from the wrong one
    embedder.model = None  # a restart learns the model again (in one process the sweep notices on its own)
    report = await embedder.sweep()
    assert report.model == "toy-embed-v2" and report.embedded == 7
    assert await index.stale_embeddings("toy-embed-v2") == []


async def test_a_failed_sweep_is_reported_and_traced_not_raised(world):
    bus, vault, index, slot, embedder = world
    slot.fail = "tei: ConnectError: all connection attempts failed"
    report = await embedder.sweep()
    assert report.embedded == 0 and report.error == slot.fail
    trace = bus.events("trace.embed")[0][1]
    assert trace["ok"] is False and "ConnectError" in trace["error"]
    assert await embedder.embed_query("anything") is None  # recall degrades, never fails


async def test_recall_falls_back_to_neighbours_only_when_nothing_exact_was_found(world):
    bus, vault, index, slot, embedder = world
    await embedder.sweep()

    pack = await recall(vault, index, "that place with the good shoyu", today=TODAY, embedder=embedder)
    assert pack.used.embedding and not pack.used.names and not pack.used.dates
    assert pack.items[0].note == "places/ramen-place-xinyi.md"
    assert pack.items[0].why.startswith("similar to the question (") and pack.items[0].excerpt

    named = await recall(vault, index, "what did Mei say about Tainan?", today=TODAY, embedder=embedder)
    assert named.used.names == ["mei"] and not named.used.embedding  # the exact rungs found something: no vectors

    embedder.min_score = 0.99
    vague = await recall(vault, index, "how is the weather", today=TODAY, embedder=embedder)
    assert vague.used.embedding and vague.items == []  # neighbours under the floor are noise

    without = await recall(vault, index, "that place with the good shoyu", today=TODAY)
    assert not without.used.embedding and without.items == []  # no embedder configured: the old behaviour


async def test_rpc_memory_embed_and_the_background_sweep_after_a_write(world):
    bus, vault, index, slot, embedder = world
    svc = MemoryService(bus, vault, index, embedder=embedder, today=lambda: TODAY)
    await svc.start()

    reply = await bus.request("rpc.memory.embed", {"id": "m9"})
    assert reply["ok"] and reply["embedded"] == 7 and reply["model"] == "toy-embed"

    reply = await bus.request(
        "rpc.memory.remember", {"note": "tainan", "type": "place", "summary": "City in the south; Mei's hometown."}
    )
    assert reply["ok"] and reply["created"]
    assert svc._sweep is not None
    await svc._sweep  # the sweep ran in the background, after the reply
    assert await index.stale_embeddings("toy-embed") == []
    found = await recall(vault, index, "the southern city", today=TODAY, embedder=embedder)
    assert "places/tainan.md" in [i.note for i in found.items]

    off = MemoryService(InMemoryBus(), vault, index)
    with pytest.raises(ValueError, match="embeddings are off"):
        await off.embed({})
