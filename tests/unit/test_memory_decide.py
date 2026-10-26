"""The decide step: the catalogue, the score-pick-hop loop and its place in recall, on the in-memory index.

The gateway's decide slot is faked with the toy embedding space from test_memory_embed: a candidate's score is
its cosine with the question, which is enough to make "pick above the floor, then hop" observable.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest

from memory.decide import Decider, catalogue, expansion
from memory.index import InMemoryIndex
from memory.indexer import reindex
from memory.recall import recall
from memory.schemas import Pick
from memory.service import MemoryService
from memory.vault import Vault
from mycelium_sdk import InMemoryBus, Message
from tests.unit.test_memory_embed import FakeEmbedSlot, toy_vector

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "vault"
TODAY = date(2026, 10, 21)


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


class FakeDecideSlot:
    """rpc.llm.decide as the gateway answers it: each candidate scored by its toy cosine with the question."""

    def __init__(self, bus: InMemoryBus) -> None:
        self.bus = bus
        self.fail: str | None = None
        self.floor: float | None = None  # what the gateway reports as the scorer's own floor
        self.calls: list[dict] = []
        self.boost: dict[str, float] = {}  # path -> score override

    async def start(self) -> None:
        await self.bus.subscribe("rpc.llm.decide", self._decide)

    async def _decide(self, msg: Message) -> None:
        self.calls.append(msg.data)
        if self.fail:
            await msg.respond({"ok": False, "error": self.fail})
            return
        q = toy_vector(msg.data["query"])
        scores = []
        for c in msg.data["candidates"]:
            score = round(_cosine(q, toy_vector(c["text"])), 4)
            if c["text"].startswith(("linked from mei:", "links to mei:")):  # it reads the hop's context
                score = min(1.0, round(score + 0.5, 4))
            scores.append({"id": c["id"], "score": self.boost.get(c["id"], score)})
        await msg.respond(
            {
                "ok": True,
                "scores": scores,
                "model": "toy-scorer",
                "provider": "fake",
                "cost_usd": 0.001,
                "floor": self.floor,
            }
        )


@pytest.fixture
async def world(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "vault")
    bus, vault, index = InMemoryBus(), Vault(tmp_path / "vault"), InMemoryIndex()
    await reindex(vault, index)
    slot = FakeDecideSlot(bus)
    await slot.start()
    return bus, vault, index, slot


async def test_catalogue_lists_notes_period_summaries_recent_days_and_recent_facts(world):
    bus, vault, index, slot = world
    rows = await catalogue(index, TODAY)
    assert [c.id for c in rows[:7]] == [
        "hansen.md",
        "modules/expenses.md",
        "people/mei.md",
        "places/ramen-place-xinyi.md",
        "projects/mycelium.md",
        "summaries/2026/10/14.md",  # 7 days old: recent
        "summaries/2026/W42.md",
    ]
    assert all(c.via == "catalogue" for c in rows)
    mei = next(c for c in rows if c.id == "people/mei.md")
    assert mei.text.startswith("mei (小美), person.") and mei.excerpt is None
    facts = rows[7:]  # the facts of 2026-10-14, by note name; the 2026-09 ones are older than the window
    assert [c.path for c in facts] == [
        "modules/expenses.md",
        "hansen.md",
        "people/mei.md",
        "places/ramen-place-xinyi.md",
    ]
    dinner = next(c for c in facts if c.path == "places/ramen-place-xinyi.md")
    assert dinner.text == "ramen-place-xinyi, 2026-10-14: dinner with mei, 350 TWD"
    assert dinner.id.startswith("places/ramen-place-xinyi.md#2026-10-14#")
    assert dinner.excerpt == "2026-10-14 dinner with [[mei]], 350 TWD"
    old = await catalogue(index, date(2026, 11, 30))  # the day summary and the facts have aged out, the week stays
    assert [c.id for c in old] == [*[c.id for c in rows[:5]], "summaries/2026/W42.md"]


async def test_expansion_is_one_hop_out_from_the_picks_facts_included(world):
    bus, vault, index, slot = world
    picks = [Pick(id="people/mei.md", path="people/mei.md", score=0.9, round=1, via="catalogue")]
    out = await expansion(index, picks, {"people/mei.md"})
    # mei links to [[ramen-place-xinyi]] and [[taipei]] (no note); the ramen note links back, but an id comes once;
    # then mei's two dated facts, one candidate each, words kept as written and links unwrapped
    assert [(c.path, c.via) for c in out] == [
        ("places/ramen-place-xinyi.md", "linked from mei"),
        ("people/mei.md", "fact on 2026-10-14 of mei"),
        ("people/mei.md", "fact on 2026-09-02 of mei"),
    ]
    assert out[0].id == out[0].path and out[0].excerpt is None
    assert out[1].id.startswith("people/mei.md#2026-10-14#") and out[2].id.startswith("people/mei.md#2026-09-02#")
    assert out[1].text == "mei, 2026-10-14: dinner at ramen-place-xinyi, she's moving to Tainan in Dec"
    assert out[1].excerpt.startswith("2026-10-14 dinner at [[ramen-place-xinyi]]")
    assert out[2].text == 'mei, 2026-09-02: recommended the book "Project Hail Mary"'
    assert await expansion(index, picks, {c.id for c in out} | {"people/mei.md"}) == []
    assert await expansion(index, [Pick(**out[1].model_dump(exclude={"text"}), score=0.8, round=2)], set()) == []

    via_summary = await expansion(
        index,
        [Pick(id="summaries/2026/W42.md", path="summaries/2026/W42.md", score=0.8, round=1, via="catalogue")],
        set(),
    )
    assert [(c.id, c.via) for c in via_summary] == [
        ("people/mei.md", "linked from summaries/2026/W42.md"),
        ("projects/mycelium.md", "linked from summaries/2026/W42.md"),
    ]


async def test_decider_scores_picks_above_the_floor_and_hops(world):
    bus, vault, index, slot = world
    decider = Decider(bus, index, floor=0.6, rounds=2)
    report = await decider.decide("the friend who is moving to tainan", TODAY, budget=8, cause="m1")
    assert report.error is None and report.rounds == 2 and report.calls == 2 and report.model == "toy-scorer"
    first = [(p.path, p.via, p.excerpt is not None) for p in report.picked if p.round == 1]
    assert first[0] == ("people/mei.md", "catalogue", False)
    assert ("people/mei.md", "catalogue", True) in first  # her dinner fact, from the catalogue: it says Tainan
    assert ("summaries/2026/W42.md", "catalogue", False) in first
    hops = [(p.path, p.via) for p in report.picked if p.round == 2]
    assert hops == [  # best first: the older book fact carries her name; the ramen note scored 0.24 alone, 0.74 linked
        ("people/mei.md", "fact on 2026-09-02 of mei"),
        ("places/ramen-place-xinyi.md", "linked from mei"),
    ]
    assert len(slot.calls[0]["candidates"]) == 11 and slot.calls[0]["candidates"][0]["id"] == "hansen.md"
    second = {c["id"]: c["text"] for c in slot.calls[1]["candidates"]}
    assert {i.split("#")[0] for i in second} == {"places/ramen-place-xinyi.md", "projects/mycelium.md", "people/mei.md"}
    assert len(second) == 3  # the dinner fact was in the catalogue already: not scored twice
    assert second["places/ramen-place-xinyi.md"].startswith("linked from mei: ramen-place-xinyi")
    assert any(t.startswith("fact on 2026-09-02 of mei: mei, 2026-09-02: recommended") for t in second.values())
    assert report.scored == 14 and report.cost_usd == pytest.approx(0.002)
    trace = bus.events("trace.decide")[0][1]
    assert trace["ok"] and trace["cause"] == "m1" and trace["report"]["picked"][0]["path"] == "people/mei.md"

    strict = await Decider(bus, index, floor=0.99, rounds=2).decide("how is the weather", TODAY)
    assert strict.picked == [] and strict.rounds == 1 and strict.error is None  # nothing cleared the floor: one round

    capped = await Decider(bus, index, floor=0.1, rounds=3).decide("mei ramen dinner spending", TODAY, budget=2)
    assert len(capped.picked) == 2 and capped.rounds == 1  # the budget ended it


async def test_a_failing_slot_is_reported_and_traced_not_raised(world):
    bus, vault, index, slot = world
    slot.fail = "vllm: ConnectError: all connection attempts failed"
    report = await Decider(bus, index).decide("anything vague", TODAY)
    assert report.error == slot.fail and report.picked == [] and report.calls == 0
    assert bus.events("trace.decide")[0][1]["ok"] is False


async def test_recall_runs_the_decide_step_for_vague_questions_only(world):
    bus, vault, index, slot = world
    decider = Decider(bus, index, floor=0.6, rounds=2)
    pack = await recall(vault, index, "the friend who is moving to tainan", today=TODAY, decider=decider)
    assert pack.used.decide and pack.used.decide.rounds == 2 and pack.used.decide.model == "toy-scorer"
    assert pack.items[0].note == "people/mei.md" and pack.items[0].why == "scored 1.00 for the question"
    hop = next(i for i in pack.items if i.note == "places/ramen-place-xinyi.md")
    assert hop.why == "named in mei's fact of 2026-10-14"  # her dinner fact, picked in round one, names the place
    assert "Project Hail Mary" in pack.items[0].excerpt and "dinner at" in pack.items[0].excerpt  # facts on mei's item
    assert [i.note for i in pack.items].count("people/mei.md") == 1
    assert not pack.used.embedding

    named = await recall(vault, index, "what did Mei say?", today=TODAY, decider=decider)
    assert named.used.names == ["mei"] and named.used.decide and named.used.decide.seeds == 1  # mei seeds the loop
    assert named.items[0].why == "mei named in the query" and slot.calls[-1]["candidates"][0]["id"] != "hansen.md"


async def test_recall_falls_back_to_embeddings_when_the_decide_slot_fails(world):
    bus, vault, index, slot = world
    embed_slot = FakeEmbedSlot(bus)
    await embed_slot.start()
    from memory.embedder import Embedder

    embedder = Embedder(bus, index)
    await embedder.sweep()
    slot.fail = "gateway: budget exceeded"
    decider = Decider(bus, index, embedder=embedder)
    pack = await recall(vault, index, "that place with the good shoyu", today=TODAY, embedder=embedder, decider=decider)
    assert pack.used.decide and pack.used.decide.error == slot.fail
    assert pack.used.embedding and pack.items[0].note == "places/ramen-place-xinyi.md"

    slot.fail = None
    pack = await recall(vault, index, "that place with the good shoyu", today=TODAY, embedder=embedder, decider=decider)
    assert pack.used.decide.error is None and not pack.used.embedding  # the decide step answered: vectors not asked


async def test_service_passes_the_decider_to_recall(world):
    bus, vault, index, slot = world
    svc = MemoryService(bus, vault, index, decider=Decider(bus, index, floor=0.6), today=lambda: TODAY)
    await svc.start()
    reply = await bus.request("rpc.memory.recall", {"query": "the friend who is moving to tainan", "id": "m7"})
    assert reply["ok"] and reply["used"]["decide"]["picked"] >= 1 and reply["items"][0]["note"] == "people/mei.md"
    assert slot.calls[0]["cause"] == "m7"


async def test_the_floor_is_the_scorers_own_unless_memory_sets_one(world):
    bus, vault, index, slot = world
    loose = await Decider(bus, index).decide("the friend who is moving to tainan", TODAY)
    assert loose.floor == 0.5 and len(loose.picked) >= 2  # neither side named one: 0.5

    slot.floor = 0.9  # a scorer whose calibration says: under 0.9 it is not about the question
    strict = await Decider(bus, index).decide("the friend who is moving to tainan", TODAY)
    assert strict.floor == 0.9 and [p.path for p in strict.picked] == ["people/mei.md"]

    mine = await Decider(bus, index, floor=0.6).decide("the friend who is moving to tainan", TODAY)
    assert mine.floor == 0.6 and len(mine.picked) == 5  # MEMORY_DECIDE_FLOOR wins over the scorer's

    pack = await recall(vault, index, "the friend who is moving to tainan", today=TODAY, decider=Decider(bus, index))
    assert pack.used.decide and pack.used.decide.floor == 0.9


async def test_a_fact_written_twice_is_one_candidate(world):
    bus, vault, index, slot = world
    note = vault.read("places/ramen-place-xinyi.md")
    note.facts.append(note.facts[0].model_copy())  # consolidation wrote the same line twice
    vault.write(note)
    from memory.indexer import index_file

    await index_file(vault, index, note.path)
    rows = await catalogue(index, TODAY)
    ids = [c.id for c in rows]
    assert len(ids) == len(set(ids)) and sum(c.path == "places/ramen-place-xinyi.md" for c in rows[7:]) == 1
    report = await Decider(bus, index, floor=0.1).decide("how much was the dinner", TODAY)
    assert report.error is None and report.picked  # the gateway would have refused a repeated id


async def test_a_named_question_seeds_the_loop_so_the_scorer_picks_the_hops(world):
    bus, vault, index, slot = world
    decider = Decider(bus, index, floor=0.6, rounds=2)
    report = await decider.decide("where did I eat with mei", TODAY, seeds=["people/mei.md"], budget=8)
    assert report.seeds == 1 and report.error is None
    first = slot.calls[0]["candidates"]
    assert {c["id"].split("#")[0] for c in first} == {"places/ramen-place-xinyi.md", "people/mei.md"}  # no catalogue
    assert all(not c["text"].startswith(("hansen", "mei (")) for c in first)  # hops, not notes by themselves
    picks = [(p.path, p.via) for p in report.picked if p.round == 1]
    assert ("places/ramen-place-xinyi.md", "linked from mei") in picks
    assert ("people/mei.md", "fact on 2026-10-14 of mei") in picks
    assert "people/mei.md" not in {p.id for p in report.picked}  # the seed itself is never a pick

    pack = await recall(vault, index, "where did I eat with Mei?", today=TODAY, decider=decider)
    assert pack.used.names == ["mei"] and pack.used.decide and pack.used.decide.seeds == 1
    assert pack.items[0].note == "people/mei.md" and pack.items[0].why == "mei named in the query"
    assert "dinner at [[ramen-place-xinyi]]" in pack.items[0].excerpt  # her dinner fact, picked, shows on her item
    ramen = next(i for i in pack.items if i.note == "places/ramen-place-xinyi.md")
    assert ramen.why.startswith("linked from mei, scored ")
    assert not pack.used.embedding

    plain = await recall(vault, index, "where did I eat with Mei?", today=TODAY)  # no decider: every link, in order
    assert [i.why for i in plain.items][:2] == ["mei named in the query", "linked from people/mei.md"]


async def test_the_notes_a_picked_fact_names_are_opened_even_when_the_link_itself_scored_low(world):
    bus, vault, index, slot = world
    slot.boost["places/ramen-place-xinyi.md"] = 0.0  # the scorer does not rate the ramen note's own line
    pack = await recall(vault, index, "where did I eat with Mei?", today=TODAY, decider=Decider(bus, index, floor=0.6))
    assert "dinner at [[ramen-place-xinyi]]" in pack.items[0].excerpt  # the fact was picked
    ramen = next(i for i in pack.items if i.note == "places/ramen-place-xinyi.md")
    assert ramen.why == "named in mei's fact of 2026-10-14"  # and the place it names is opened for it
