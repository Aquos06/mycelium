"""Recall: dates, names, links, then (later) embeddings. A small program, not a vector search."""

from datetime import date
from pathlib import Path

import pytest

from memory.index import InMemoryIndex
from memory.indexer import reindex
from memory.recall import find_names, lookup, recall, resolve_dates
from memory.vault import Vault

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "vault"
TODAY = date(2026, 10, 21)  # a Wednesday


@pytest.mark.parametrize(
    "query,expected",
    [
        ("what happened today", [date(2026, 10, 21)]),
        ("what did I do yesterday?", [date(2026, 10, 20)]),
        ("who did I have dinner with last Wednesday?", [date(2026, 10, 14)]),  # same weekday -> 7 days ago
        ("last tuesday", [date(2026, 10, 20)]),  # most recent Tuesday before today
        ("on 2026-10-14 I", [date(2026, 10, 14)]),
        ("nothing about time", []),
        ("yesterday and 2026-10-01", [date(2026, 10, 20), date(2026, 10, 1)]),
    ],
)
def test_resolve_dates(query, expected):
    assert [d for _, d in resolve_dates(query, TODAY)] == expected


async def test_find_names_exact_alias_and_cjk_substring():
    index = InMemoryIndex()
    await reindex(Vault(FIXTURES), index)
    assert await find_names("what did 小美 say about Tainan?", index) == [("小美", "mei", "alias")]
    assert await find_names("dinner at Menya Xinyi with Mei", index) == [
        ("menya xinyi", "ramen-place-xinyi", "alias"),
        ("mei", "mei", "exact"),  # the note's own name, even though it is also listed as an alias
    ]
    assert await find_names("how is spending this month", index) == [("spending", "expenses", "alias")]


async def test_find_names_fuzzy_only_for_capitalised_unknown_words():
    index = InMemoryIndex()
    await reindex(Vault(FIXTURES), index)
    assert await find_names("what did Meii say", index) == [("meii", "mei", "fuzzy")]
    # lowercase words never go through fuzzy, so ordinary words don't turn into people
    assert await find_names("what a nice meal", index) == []


async def test_lookup_reports_how_it_matched():
    index = InMemoryIndex()
    await reindex(Vault(FIXTURES), index)
    assert [(m.record.name, m.via) for m in await lookup(index, "mei")] == [("mei", "exact")]
    assert [(m.record.name, m.via) for m in await lookup(index, "小美")] == [("mei", "alias")]
    m = (await lookup(index, "Meii"))[0]
    assert (m.record.name, m.via) == ("mei", "fuzzy") and 0.3 <= m.score < 1
    assert await lookup(index, "zzzz") == []


async def test_recall_by_date_follows_links_from_the_day_summary():
    vault = Vault(FIXTURES)
    index = InMemoryIndex()
    await reindex(vault, index)

    pack = (
        await recall(vault, index, "who did I have dinner with last Wednesday?", today=TODAY, budget=8)
    ).model_dump()

    assert pack["query"] == "who did I have dinner with last Wednesday?"
    assert pack["used"] == {"dates": ["2026-10-14"], "names": [], "embedding": False}
    notes = [item["note"] for item in pack["items"]]
    assert notes[0] == "summaries/2026/10/14.md"
    assert set(notes[1:]) >= {"people/mei.md", "places/ramen-place-xinyi.md"}
    day_item = pack["items"][0]
    assert day_item["why"] == "last Wednesday = 2026-10-14"
    mei_item = next(i for i in pack["items"] if i["note"] == "people/mei.md")
    assert mei_item["why"] == "linked from summaries/2026/10/14.md"
    assert "Tainan" in mei_item["excerpt"]  # the fact from that day is the excerpt
    assert pack["budget"]["max"] == 8 and pack["budget"]["notes_opened"] == len(pack["items"])


async def test_recall_by_name_opens_note_and_one_hop():
    vault = Vault(FIXTURES)
    index = InMemoryIndex()
    await reindex(vault, index)

    pack = (await recall(vault, index, "what did 小美 say about Tainan?", today=TODAY, budget=8)).model_dump()

    assert pack["used"]["names"] == ["mei"] and pack["used"]["dates"] == []
    notes = [item["note"] for item in pack["items"]]
    assert notes[0] == "people/mei.md"
    assert "places/ramen-place-xinyi.md" in notes  # one hop via [[ramen-place-xinyi]]
    assert "hansen.md" not in notes  # taipei is linked but has no note; nothing to open
    mei_item = pack["items"][0]
    assert mei_item["why"] == "小美 is an alias of mei"
    assert "Tainan" in mei_item["excerpt"]  # facts mentioning query words win the excerpt


async def test_recall_always_includes_today_and_yesterday_when_they_exist():
    vault = Vault(FIXTURES)
    index = InMemoryIndex()
    await reindex(vault, index)
    # the fixture has a summary for 10-14 only; asking on 10-15 should include it as "yesterday"
    pack = (await recall(vault, index, "anything new?", today=date(2026, 10, 15), budget=8)).model_dump()
    assert [i["note"] for i in pack["items"]] == ["summaries/2026/10/14.md"]
    assert pack["items"][0]["why"] == "yesterday"


async def test_recall_respects_budget():
    vault = Vault(FIXTURES)
    index = InMemoryIndex()
    await reindex(vault, index)
    pack = (
        await recall(vault, index, "dinner with 小美 at Menya Xinyi last Wednesday", today=TODAY, budget=2)
    ).model_dump()
    assert len(pack["items"]) == 2
    assert pack["budget"] == {"notes_opened": 2, "max": 2}


async def test_recall_with_nothing_to_go_on_returns_empty_pack():
    vault = Vault(FIXTURES)
    index = InMemoryIndex()
    await reindex(vault, index)
    pack = (await recall(vault, index, "tell me a joke", today=TODAY, budget=8)).model_dump()
    assert pack["items"] == []
    assert pack["used"]["embedding"] is False  # no embeddings yet; the fallback reports it was not used
