"""Nightly consolidation: a day of events -> write_day -> the summary, facts with provenance, new notes. Idempotent."""

import json
import shutil
from datetime import UTC, date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from memory.consolidate import (
    TOOL_NAME,
    WRITE_DAY_TOOL,
    ConsolidationError,
    Consolidator,
    render_events,
)
from memory.events import JsonlEvents
from memory.index import InMemoryIndex
from memory.indexer import reindex
from memory.schedule import next_run
from memory.schemas import DayDigest
from memory.service import MemoryService
from memory.vault import Vault
from mycelium_sdk import InMemoryBus, Message

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EVENTS = FIXTURES / "events" / "2026-10-14.jsonl"
DAY = date(2026, 10, 14)
TZ = "Asia/Taipei"

DIGEST = {
    "summary": (
        "Climbed with [[mei]] in the evening, then ramen at [[ramen-place-xinyi]]; she is moving to [[tainan]] "
        "in December. Afternoon on [[mycelium]] docs; the [[expenses]] module went live. 615 TWD spent."
    ),
    "facts": [
        # the fixture note already has this fact from the same event -> skipped
        {"note": "mei", "text": "dinner at [[ramen-place-xinyi]], she's moving to Tainan in Dec", "events": [48213]},
        {"note": "Hansen", "text": "climbed with [[mei]], then ramen in Xinyi", "events": [48209, 48213]},
        {
            "note": "tainan",
            "type": "place",
            "aliases": ["台南"],
            "text": "[[mei]] is moving here in December",
            "events": [48213],
        },
        {"note": "mycelium", "text": "docs switched to a layered architecture", "events": [99999]},  # unknown id
    ],
    "updates": [{"note": "ramen-place-xinyi", "summary": "Ramen shop near Xinyi Anhe; [[mei]]'s pick for dinner."}],
}


class FakeGateway:
    def __init__(self, bus: InMemoryBus):
        self.bus = bus
        self.replies: list[dict] = []
        self.requests: list[dict] = []

    async def start(self):
        await self.bus.subscribe("rpc.llm.complete", self._complete)

    async def _complete(self, msg: Message):
        self.requests.append(msg.data)
        await msg.respond(self.replies.pop(0))


def tool_reply(input, id="t1", cost=0.002):
    return {
        "ok": True,
        "text": "",
        "tool_calls": [{"id": id, "name": TOOL_NAME, "input": input}],
        "stop_reason": "tool_use",
        "model": "claude-haiku-5-5",
        "provider": "claude",
        "usage": {"input_tokens": 900, "output_tokens": 300},
        "cost_usd": cost,
    }


@pytest.fixture
async def world(tmp_path):
    shutil.copytree(FIXTURES / "vault", tmp_path / "vault")
    vault, index = Vault(tmp_path / "vault"), InMemoryIndex()
    await reindex(vault, index)
    bus = InMemoryBus()
    gw = FakeGateway(bus)
    await gw.start()
    c = Consolidator(bus, vault, index, JsonlEvents(EVENTS), tz=TZ)
    return SimpleNamespace(bus=bus, gw=gw, vault=vault, index=index, c=c)


# ---- prompt and schema ------------------------------------------------------------------------------


async def test_render_events_is_one_compact_line_each_and_capped():
    events = await JsonlEvents(EVENTS).for_day(DAY, TZ)
    text = render_events(events, max_chars=100_000)
    lines = text.splitlines()
    assert len(lines) == len(events) == 14  # requests, traces and the next local day are not material
    assert lines[0] == "#48201 07:52 sense.chat (telegram): coffee 85"
    assert any(line.startswith("#48203 07:52 brain.observe (expenses): coffee 85 TWD") for line in lines)
    capped = render_events(events, max_chars=200)
    assert capped.splitlines()[-1].startswith("...") and "omitted" in capped


def test_digest_schema_validates_slugs_and_text():
    d = DayDigest.model_validate(
        {"summary": " a day ", "facts": [{"note": " Mei ", "text": "went  home", "aliases": ["小美", "Mei"]}]}
    )
    assert d.summary == "a day" and d.facts[0].note == "mei" and d.facts[0].text == "went home"
    assert d.facts[0].aliases == ["小美", "mei"]
    with pytest.raises(ValidationError, match="slug"):
        DayDigest.model_validate({"summary": "x", "facts": [{"note": "../etc", "text": "y"}]})
    with pytest.raises(ValidationError, match="summary"):
        DayDigest.model_validate({"summary": "   "})
    schema = WRITE_DAY_TOOL["input_schema"]
    assert schema["required"] == ["summary"] and "title" not in json.dumps(schema)
    assert schema["properties"]["facts"]["items"]["properties"]["type"]["enum"][0] == "self"


# ---- the run ----------------------------------------------------------------------------------------


async def test_consolidation_writes_the_summary_facts_and_notes(world):
    world.gw.replies = [tool_reply(DIGEST)]
    mei_before = world.vault.read("people/mei.md").facts

    report = await world.c.run(DAY, cause="nightly-1")

    req = world.gw.requests[0]
    assert req["slot"] == "consolidate" and req["tool_choice"] == TOOL_NAME and req["tools"][0]["name"] == TOOL_NAME
    assert req["cause"] == "nightly-1" and req["timeout"] == world.c.timeout and req["max_tokens"] == 4096
    prompt = req["messages"][0]["content"]
    assert "Day: Wednesday 2026-10-14 (Asia/Taipei)" in prompt
    assert "- mei (person; aliases: mei, 小美): Friend from the climbing gym" in prompt
    assert "#48213 21:05 sense.chat (telegram): dinner 350" in prompt and "Events (14)" in prompt

    assert report.events == 14 and report.rounds == 1 and report.model == "claude-haiku-5-5"
    assert report.facts_added == 3 and report.facts_skipped == 1 and report.cost_usd == 0.002
    assert report.notes_created == ["tainan"] and report.notes_updated == [
        "hansen",
        "mei",
        "mycelium",
        "ramen-place-xinyi",
    ]

    # the day summary replaces the fixture's and is indexed with its links
    assert report.summary_path == "summaries/2026/10/14.md"
    assert (world.vault.root / "summaries/2026/10/14.md").read_text() == DIGEST["summary"] + "\n"
    s = await world.index.summary("day", "2026-10-14")
    assert s.text == DIGEST["summary"] and "tainan" in s.links

    # facts: provenance from the event named, `consolidation` when the id is unknown, no duplicates
    assert world.vault.read("people/mei.md").facts == mei_before
    hansen = world.vault.read("hansen.md")
    assert hansen.facts[0].day == DAY and hansen.facts[0].source == "ev:48209"
    assert hansen.facts[0].text == "climbed with [[mei]], then ramen in Xinyi"
    assert world.vault.read("projects/mycelium.md").facts[0].source == "consolidation"

    tainan = world.vault.read("places/tainan.md")
    assert tainan.type == "place" and tainan.aliases == ["台南"] and tainan.facts[0].source == "ev:48213"
    assert (await world.index.get("tainan")).path == "places/tainan.md"
    assert (await world.index.by_alias("台南"))[0].name == "tainan"

    assert world.vault.read("places/ramen-place-xinyi.md").summary == DIGEST["updates"][0]["summary"]

    trace = world.bus.events("trace.consolidate")[0][1]
    assert trace["ok"] and trace["cause"] == "nightly-1" and trace["hops"] == 1 and trace["source"] == "memory"
    assert trace["report"]["facts_added"] == 3 and trace["report"]["cost_usd"] == 0.002


async def test_rerunning_a_day_changes_nothing(world):
    world.gw.replies = [tool_reply(DIGEST), tool_reply(DIGEST)]
    first = await world.c.run(DAY)
    files_after_first = {p: world.vault.raw(p) for p in world.vault.paths()}
    second = await world.c.run(DAY)
    assert first.facts_added == 3 and second.facts_added == 0 and second.facts_skipped == 4
    assert second.notes_created == [] and {p: world.vault.raw(p) for p in world.vault.paths()} == files_after_first


async def test_an_invalid_digest_goes_back_to_the_model_once(world):
    world.gw.replies = [tool_reply({"facts": [{"note": "mei", "text": "x"}]}, id="bad"), tool_reply(DIGEST, id="good")]
    report = await world.c.run(DAY)
    assert report.rounds == 2 and report.cost_usd == 0.004 and report.facts_added == 3
    retry = world.gw.requests[1]["messages"]
    assert retry[1]["content"][0] == {
        "type": "tool_use",
        "id": "bad",
        "name": TOOL_NAME,
        "input": {"facts": [{"note": "mei", "text": "x"}]},
    }
    assert retry[2]["content"][0]["type"] == "tool_result" and "summary" in retry[2]["content"][0]["content"]

    world.gw.replies = [tool_reply({}, id="b1"), tool_reply({}, id="b2")]
    with pytest.raises(ConsolidationError, match="no valid digest after 2 rounds"):
        await world.c.run(DAY)


async def test_gateway_failure_is_a_clean_error_and_traced(world):
    world.gw.replies = [{"ok": False, "error": "budget exceeded: $30.00 of $30.00 this month"}]
    with pytest.raises(ConsolidationError, match="budget exceeded"):
        await world.c.run(DAY, cause="n2")
    trace = world.bus.events("trace.consolidate")[0][1]
    assert trace["ok"] is False and trace["error"].startswith("budget exceeded") and trace["report"]["events"] == 14
    assert not (world.vault.root / "summaries/2026/10/14.md").read_text().startswith("Climbed with")  # untouched


async def test_a_day_without_events_is_skipped_without_a_model_call(world):
    report = await world.c.run(date(2026, 1, 1))
    assert report.skipped and report.reason == "no events" and world.gw.requests == []
    assert world.bus.events("trace.consolidate")[0][1]["report"]["skipped"] is True


async def test_rpc_consolidate_defaults_to_yesterday_and_needs_a_consolidator(world):
    svc = MemoryService(world.bus, world.vault, world.index, consolidator=world.c, today=lambda: date(2026, 10, 15))
    await svc.start()
    world.gw.replies = [tool_reply(DIGEST)]
    reply = await world.bus.request("rpc.memory.consolidate", {"id": "req-1"}, timeout=5)
    assert reply["ok"] and reply["day"] == "2026-10-14" and reply["facts_added"] == 3
    assert world.gw.requests[0]["cause"] == "req-1"

    reply = await world.bus.request("rpc.memory.consolidate", {"day": "not-a-day"}, timeout=5)
    assert not reply["ok"] and reply["error"].startswith("day:")

    bare = MemoryService(InMemoryBus(), world.vault, world.index)
    await bare.start()
    reply = await bare.bus.request("rpc.memory.consolidate", {}, timeout=5)
    assert not reply["ok"] and "not configured" in reply["error"]


# ---- schedule ---------------------------------------------------------------------------------------


def test_schedule_finds_the_next_local_run():
    zone = ZoneInfo(TZ)
    before = datetime(2026, 10, 23, 1, 0, tzinfo=zone)  # 01:00 local: today at 03:30
    assert next_run(before, time(3, 30), zone) == datetime(2026, 10, 23, 3, 30, tzinfo=zone)
    after = datetime(2026, 10, 22, 20, 0, tzinfo=UTC)  # 04:00 local on the 23rd: tomorrow
    assert next_run(after, time(3, 30), zone) == datetime(2026, 10, 24, 3, 30, tzinfo=zone)


def test_autolink_wraps_known_names_once_and_leaves_existing_links_alone():
    from memory.consolidate import autolink

    vocab = [
        ("mei", "mei"),
        ("小美", "mei"),
        ("menya xinyi", "ramen-place-xinyi"),
        ("ramen-place-xinyi", "ramen-place-xinyi"),
    ]
    text = "Dinner with 小美 at Menya Xinyi; 小美 is moving. Meiling came too."
    out = autolink(text, vocab)
    assert out == "Dinner with [[mei|小美]] at [[ramen-place-xinyi|Menya Xinyi]]; 小美 is moving. Meiling came too."
    assert autolink("Saw [[mei]] and 小美 again", vocab) == "Saw [[mei]] and 小美 again"  # already linked: left alone
    assert autolink("nothing known here", vocab) == "nothing known here"


async def test_prompt_lists_what_the_day_already_has_so_the_model_does_not_repeat_it(world):
    world.gw.replies = [tool_reply({"summary": "quiet day"})]
    await world.c.run(DAY)
    prompt = world.gw.requests[0]["messages"][0]["content"]
    assert "Already recorded for this day (do not repeat):" in prompt
    assert "- mei: dinner at [[ramen-place-xinyi]], she's moving to Tainan in Dec (ev:48213)" in prompt
    assert "- hansen: switched the project docs to a layered architecture (ev:48204)" in prompt
