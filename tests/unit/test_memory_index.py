"""Index: a searchable copy of the vault, written only by the indexer."""

from datetime import date
from pathlib import Path

import pytest

from memory.index import InMemoryIndex, trigram_similarity
from memory.indexer import index_file, reindex
from memory.vault import Fact, Note, Vault

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "vault"


@pytest.mark.parametrize(
    "a,b,low,high",
    [
        ("mei", "mei", 1.0, 1.0),
        ("meii", "mei", 0.45, 0.55),  # pg_trgm gives 0.5
        ("mey", "mei", 0.3, 0.4),
        ("dinner", "mei", 0.0, 0.1),
    ],
)
def test_trigram_similarity_matches_pg_trgm(a, b, low, high):
    s = trigram_similarity(a, b)
    assert low <= s <= high


async def test_reindex_fills_notes_links_facts_summaries():
    index = InMemoryIndex()
    stats = await reindex(Vault(FIXTURES), index)
    assert stats.notes == 5 and stats.summaries == 2 and stats.skipped == 0

    mei = await index.get("mei")
    assert mei is not None
    assert mei.path == "people/mei.md" and mei.type == "person"
    assert mei.aliases == ["mei", "小美"]
    assert mei.links == ["taipei", "ramen-place-xinyi"]

    facts = await index.facts(name="mei")
    assert [f.day for f in facts] == [date(2026, 10, 14), date(2026, 9, 2)]
    assert facts[0].source == "ev:48213"

    by_day = await index.facts(day=date(2026, 10, 14))
    assert {f.note for f in by_day} == {"hansen", "mei", "ramen-place-xinyi", "expenses"}

    back = await index.backlinks("mei")
    assert {r.name for r in back} == {"ramen-place-xinyi"}  # notes only; summaries are separate

    day = await index.summary("day", "2026-10-14")
    assert day is not None and "[[mei]]" in day.text and "ramen-place-xinyi" in day.links
    assert await index.summary("day", "2026-10-15") is None


async def test_reindex_skips_unchanged_files():
    index = InMemoryIndex()
    await reindex(Vault(FIXTURES), index)
    again = await reindex(Vault(FIXTURES), index)
    assert again.notes == 0 and again.summaries == 0 and again.skipped == 7


async def test_index_file_replaces_links_and_facts(tmp_path):
    vault = Vault(tmp_path)
    index = InMemoryIndex()
    note = Note(
        name="bike",
        path="things/bike.md",
        type="thing",
        summary="Bike. [[garage]]",
        links=["garage"],
        facts=[Fact(day=date(2026, 1, 1), text="bought")],
    )
    vault.write(note)
    await index_file(vault, index, "things/bike.md")
    assert {r.name for r in await index.backlinks("garage")} == {"bike"}

    note.links = ["shed"]
    note.summary = "Bike. [[shed]]"
    note.facts = []
    vault.write(note)
    await index_file(vault, index, "things/bike.md")
    assert await index.backlinks("garage") == []
    assert {r.name for r in await index.backlinks("shed")} == {"bike"}
    assert await index.facts(name="bike") == []


async def test_lookup_ladder_exact_alias_fuzzy():
    index = InMemoryIndex()
    await reindex(Vault(FIXTURES), index)

    assert (await index.get("mei")).name == "mei"
    assert (await index.get("MEI")).name == "mei"  # names are case-insensitive
    assert await index.get("nobody") is None

    assert [r.name for r in await index.by_alias("小美")] == ["mei"]
    assert [r.name for r in await index.by_alias("Menya Xinyi")] == ["ramen-place-xinyi"]
    assert await index.by_alias("ramen") == []

    fuzzy = await index.fuzzy("meii", limit=3)
    assert fuzzy[0][0].name == "mei" and fuzzy[0][1] >= 0.3
    assert await index.fuzzy("zzzzzz") == []


async def test_vocabulary_lists_every_name_and_alias():
    index = InMemoryIndex()
    await reindex(Vault(FIXTURES), index)
    vocab = dict(await index.vocabulary())
    assert vocab["mei"] == "mei" and vocab["小美"] == "mei" and vocab["那家拉麵"] == "ramen-place-xinyi"
    assert vocab["spending"] == "expenses"


async def test_delete_note_removes_everything(tmp_path):
    index = InMemoryIndex()
    await reindex(Vault(FIXTURES), index)
    await index.delete_note("people/mei.md")
    assert await index.get("mei") is None
    assert await index.facts(name="mei") == []
    assert await index.by_alias("小美") == []
