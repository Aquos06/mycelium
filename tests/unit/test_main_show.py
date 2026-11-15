"""`show`: a module's data under Main's reply, by a module's view (Main gets the data) or by the reply of a request
called this turn. The numbers are the module's: `show` names where they are, never what they are. How blocks are
made is the SDK's (test_blocks.py)."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from main.blocks import MAX_BLOCKS, TurnData
from main.schemas import PlanTrace
from main.service import MainService
from main.thread import ThreadStore
from main.tools import ToolContext, default_tools
from mycelium_sdk import InMemoryBus, InMemoryKV, Message, validate_manifest
from mycelium_sdk.blocks import Formatter
from tests.unit.test_blocks import SPENDING, WATER
from tests.unit.test_main import TODAY, World, call, chat, say

FMT = Formatter(currency="TWD", zone=ZoneInfo("Asia/Taipei"), today=date(2026, 11, 7))


# ---- the tool ------------------------------------------------------------------------------------------------


async def run_show(turn: TurnData, **args):
    ctx = ToolContext(bus=InMemoryBus(), turn=turn)
    return await default_tools().call("show", {"source": "spending.summary", **args}, ctx)


async def test_show_draws_only_on_what_a_module_answered_this_turn():
    turn = TurnData(formatter=FMT)
    outcome = await run_show(turn, kind="stats")
    assert outcome.result == {
        "ok": False,
        "error": "no reply from spending.summary in this turn: call ask_module for it first (asked so far: none yet)",
    }
    turn.replies["spending.summary"] = SPENDING
    outcome = await run_show(turn, kind="stats")
    assert outcome.result == {"ok": True, "shown": "stats: Total NT$3,420, Count 6"}
    assert len(turn.blocks) == 1
    bad = await run_show(turn, kind="chart", path="nowhere")
    assert bad.ok is False and "no 'nowhere'" in bad.result["error"] and len(turn.blocks) == 1


async def test_a_request_named_as_a_view_or_no_source_shows_the_reply_asked():
    turn = TurnData(formatter=FMT, replies={"spending.summary": SPENDING})
    shown = "stats: Total NT$3,420, Count 6"
    assert (await run_show(turn, kind="stats", source="", view="spending.summary")).result == {
        "ok": True,
        "shown": shown,
    }
    for named in ({"view": "spending"}, {}):  # Main chose: it says which
        outcome = await run_show(turn, kind="stats", source="", **named)
        assert outcome.result == {"ok": True, "shown": shown, "from": "spending.summary"}, named
    both = await run_show(turn, kind="stats", source="spending.summary", view="spending.weak")
    assert both.ok  # the source given, the view not listed


@pytest.mark.parametrize(
    "named",
    [
        {"source": "spending.history"},  # a request not asked yet (the supervisor silent: no module list)
        {"source": "spending.histroy"},  # mistyped
        {"view": "spending.week", "source": ""},  # a view not listed
    ],
)
async def test_a_name_that_says_another_reply_is_never_swapped_for_the_one_asked(named):
    turn = TurnData(formatter=FMT, replies={"spending.summary": SPENDING})
    outcome = await run_show(turn, kind="table", **named)
    assert outcome.ok is False and turn.blocks == []
    if named.get("view"):
        assert outcome.result["error"].startswith("no view 'spending.week'; the views under Modules: none. To show")
    else:
        assert outcome.result["error"].startswith(f"no reply from {named['source']} in this turn: call ask_module")


async def test_with_two_replies_show_needs_the_one_meant():
    turn = TurnData(formatter=FMT, replies={"spending.summary": SPENDING, "water.today": WATER})
    outcome = await run_show(turn, kind="stats", source="")
    assert outcome.result["error"] == "several replies this turn: name one as `source` (spending.summary, water.today)"
    assert (await run_show(turn, kind="stats", source="water")).ok  # the only reply of that module
    turn.replies["spending.history"] = SPENDING
    mine = await run_show(turn, kind="stats", source="spending")
    assert mine.result["error"] == (
        "several replies from spending this turn: name one as `source` (spending.summary, spending.history)"
    )


@pytest.mark.parametrize(
    ("args", "x", "series"),
    [
        ({"fields": ["day", "total"]}, "day", ["total"]),  # by_day: every field there
        ({"fields": ["category", "total"]}, "category", ["value"]),  # by_category: one there, its value by position
        ({"fields": ["category", "amount"]}, "category", ["amount"]),  # every field there wins: the expenses
        ({"fields": ["day", "total"], "path": "spending.summary"}, "day", ["total"]),  # the source again
        ({"fields": ["day", "total"], "path": "by_category"}, "category", ["value"]),  # a path given that fits stays
    ],
)
async def test_a_chart_finds_its_data_where_its_fields_are(args, x, series):
    turn = TurnData(formatter=FMT, replies={"spending.summary": SPENDING})
    outcome = await run_show(turn, kind="chart", **args)
    assert outcome.ok, outcome.result
    (block,) = turn.blocks
    assert (block.x.key, [s.key for s in block.series]) == (x, series)
    if args.get("path") != "by_category":  # Main chose the place: it says which
        assert outcome.result["from"].startswith("spending.summary, path ")


async def test_a_table_or_stats_find_theirs_too():
    turn = TurnData(formatter=FMT, replies={"spending.summary": SPENDING})
    table = await run_show(turn, kind="table", fields=["day", "description", "category", "amount"])
    assert table.ok and turn.blocks[0].total == 2  # the expenses
    stats = await run_show(turn, kind="stats", path="total, count")
    assert stats.result == {
        "ok": True,
        "shown": "stats: Total NT$3,420, Count 6",
        "from": "spending.summary, the whole reply",
    }


async def test_an_empty_list_is_said_as_empty():
    turn = TurnData(formatter=FMT, replies={"shopping.list": {"ok": True, "items": []}})
    outcome = await run_show(turn, kind="table", source="shopping.list")
    assert outcome.result == {"ok": False, "error": "nothing in the reply of shopping.list to show: items is empty"}


async def test_a_reply_with_one_place_takes_the_fields_by_position():
    stats = {"ok": True, "days": {"2026-11-01": 3, "2026-11-02": 5}}  # what hello.stats answers
    turn = TurnData(formatter=FMT, replies={"hello.stats": stats})
    outcome = await run_show(turn, kind="chart", source="hello.stats", fields=["date", "count"])
    assert outcome.ok, outcome.result
    assert [(c.key, c.label) for c in (turn.blocks[0].x, *turn.blocks[0].series)] == [
        ("days", "Date"),
        ("value", "Count"),
    ]


async def test_where_several_places_fit_show_names_them():
    turn = TurnData(formatter=FMT, replies={"spending.summary": SPENDING})
    outcome = await run_show(turn, kind="table")  # not a table of the reply's mixed top
    assert outcome.result["error"] == (
        "that fits several places in the reply of spending.summary: name one as `path` (by_category: category, "
        "value; by_day: day, total; expenses: id, day, amount, category, description)"
    )
    missing = await run_show(turn, kind="chart", fields=["week", "steps"])
    assert missing.result["error"].startswith("no place in the reply of spending.summary fits a chart of those fields")
    assert turn.blocks == []


async def test_show_stops_at_a_few_blocks():
    turn = TurnData(formatter=FMT, replies={"spending.summary": SPENDING})
    for _ in range(MAX_BLOCKS):
        assert (await run_show(turn, kind="stats")).ok
    assert "enough for one reply" in (await run_show(turn, kind="stats")).result["error"]


# ---- through Main ----------------------------------------------------------------------------------------------


@pytest.fixture
async def world():
    bus = InMemoryBus()
    w = World(bus, [])
    w.modules = [
        {"name": "spending", "status": "running", "manifest": {"purpose": "Tracks spending.", "requests": ["summary"]}}
    ]
    await w.start()

    async def spending(msg: Message):
        await msg.respond(SPENDING)

    await bus.subscribe("rpc.mod.spending.summary", spending)
    w.svc = MainService(bus, ThreadStore(InMemoryKV(), max_turns=6), today=lambda: TODAY, currency="USD")
    await w.svc.start()
    return w


ASK_SPENDING = {"module": "spending", "action": "summary", "args": {}}


async def test_the_blocks_go_out_with_the_reply(world):
    world.llm_script = [
        call("ask_module", ASK_SPENDING),
        call("show", {"kind": "chart", "source": "spending.summary", "path": "by_category"}, id="t2"),
        say("Food is most of it."),
    ]
    await world.send("sense.chat", chat("where did my money go?").data)
    out = world.bus.events("out.say")[-1][1]
    assert out["text"] == "Food is most of it."
    assert [(b["kind"], b["points"][0]["x"]["s"]) for b in out["blocks"]] == [("chart", "food")]
    # the planner was told what it showed, so it need not write it out
    shown = world.llm_requests[-1]["messages"][-1]["content"][0]["content"]
    assert '"shown": "a bar chart of Value by Category, 4 points"' in shown
    trace = PlanTrace.model_validate(world.bus.events("trace.plan")[-1][1])
    assert [t.name for t in trace.tools] == ["ask_module", "show"]
    # the thread keeps the call, so a later turn knows what was on screen
    turns = (await world.svc.store.load("telegram", "123")).turns
    assert [c.name for c in turns[-1].calls] == ["ask_module", "show"]


async def test_money_is_in_mains_currency(world):
    world.llm_script = [
        call("ask_module", ASK_SPENDING),
        call("show", {"kind": "stats", "source": "spending.summary"}, id="t2"),
        say("ok"),
    ]
    await world.send("sense.chat", chat("spending numbers").data)
    stats = world.bus.events("out.say")[-1][1]["blocks"][0]["stats"]
    assert stats[0] == {"label": "Total", "value": {"v": 3420.0, "s": "$3,420"}}


async def test_each_turn_starts_with_nothing_to_show(world):
    world.llm_script = [call("ask_module", ASK_SPENDING), say("ok")]
    await world.send("sense.chat", chat("spending").data)
    world.llm_script = [call("show", {"kind": "stats", "source": "spending.summary"}), say("here")]
    await world.send("sense.chat", chat("show it").data)
    out = world.bus.events("out.say")[-1][1]
    assert out["blocks"] == []  # last turn's reply is not this turn's: ask the module again


async def test_a_turn_that_fails_says_so_without_half_its_answer(world):
    world.llm_script = [
        call("ask_module", ASK_SPENDING),
        call("show", {"kind": "stats", "source": "spending.summary"}, id="t2"),
        {"ok": False, "error": "timed out"},
    ]
    await world.send("sense.chat", chat("spending").data)
    out = world.bus.events("out.say")[-1][1]
    assert out["blocks"] == [] and "took too long" in out["text"]


# ---- by a module's view --------------------------------------------------------------------------------------

VIEWS = {
    "week": {"title": "This week", "request": "summary", "args": {"from": "$week_start"}, "show": "stats"},
    "by_category": {"title": "By category", "request": "summary", "path": "by_category", "show": "chart"},
    "sneaky": {"request": "add", "show": "stats"},  # writes: never a view
}
MANIFEST = {  # as the supervisor serves it: validated (validate_manifest below)
    "name": "spending",
    "purpose": "Tracks spending, with totals by category.",
    "requests": {
        "summary": {
            "description": "Totals since a day.",
            "params": {"from": "optional date"},
            "returns": {"total": "number", "by_category": "map"},
        },
        "add": {"description": "Store one expense.", "params": {"amount": "number"}},
    },
    "views": VIEWS,
}


@pytest.fixture
async def viewed():
    bus = InMemoryBus()
    w = World(bus, [])
    w.modules = [
        {"name": "spending", "status": "running", "manifest": validate_manifest(MANIFEST).model_dump(mode="json")}
    ]
    await w.start()
    w.asked = []

    async def summary(msg: Message):
        w.asked.append(msg.data)
        await msg.respond(SPENDING)

    await bus.subscribe("rpc.mod.spending.summary", summary)
    w.svc = MainService(bus, ThreadStore(InMemoryKV(), max_turns=6), today=lambda: TODAY)
    await w.svc.start()
    return w


async def test_the_planner_sees_each_module_s_views_and_never_one_that_writes(viewed):
    viewed.llm_script = [say("ok")]
    await viewed.send("sense.chat", chat("hi").data)
    system = viewed.llm_requests[-1]["system"]
    assert (
        "Views (`show` one by name): spending.week (This week, stats), spending.by_category (By category, chart)"
        in system
    )
    assert "spending.sneaky" not in system


async def test_show_by_view_asks_the_module_for_that_view_s_data(viewed):
    viewed.llm_script = [call("show", {"view": "spending.week"}), say("You spent NT$3,420 since Monday.")]
    await viewed.send("sense.chat", chat("how much this week?").data)
    out = viewed.bus.events("out.say")[-1][1]
    assert [(b["kind"], b["title"]) for b in out["blocks"]] == [("stats", "This week")]
    monday = TODAY.fromordinal(TODAY.toordinal() - TODAY.weekday()).isoformat()
    assert viewed.asked == [{"from": monday}]  # the view's $week_start, worked out today


async def test_a_view_that_is_not_listed_is_refused_with_the_ones_that_are(viewed):
    viewed.llm_script = [call("show", {"view": "spending.sneaky"}), say("ok")]
    await viewed.send("sense.chat", chat("show it").data)
    result = viewed.llm_requests[-1]["messages"][-1]["content"][0]["content"]
    assert "no view 'spending.sneaky'; the views under Modules: spending.week, spending.by_category" in result
    assert viewed.bus.events("out.say")[-1][1]["blocks"] == []


async def test_show_needs_a_view_or_a_reply_asked_this_turn():
    outcome = await default_tools().call("show", {"title": "x"}, ToolContext(bus=InMemoryBus(), turn=TurnData()))
    assert outcome.result == {
        "ok": False,
        "error": "give a `view` listed under Modules, or a `source` you called with ask_module in this turn "
        "(asked so far: none yet)",
    }
