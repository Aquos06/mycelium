"""`show`: a module's reply this turn as a block under Main's reply (table, chart, stats, details, meter). The
numbers are the module's: `show` names where they are, never what they are."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from main.blocks import (
    MAX_BARS,
    MAX_BLOCKS,
    MAX_ROWS,
    ChartBlock,
    DetailsBlock,
    Format,
    Formatter,
    MeterBlock,
    ShowArgs,
    ShowError,
    StatsBlock,
    TableBlock,
    TurnData,
    build,
)
from main.schemas import PlanTrace
from main.service import MainService
from main.thread import ThreadStore
from main.tools import ToolContext, default_tools
from mycelium_sdk import InMemoryBus, InMemoryKV, Message
from tests.unit.test_main import TODAY, World, call, chat, say

FMT = Formatter(currency="TWD", zone=ZoneInfo("Asia/Taipei"), today=date(2026, 11, 7))
SPENDING = {
    "ok": True,
    "total": 3420,
    "count": 6,
    "by_category": {"coffee": 740, "food": 1820, "transport": 520, "other": 340},
    "by_day": [
        {"day": "2026-11-02", "total": 820},
        {"day": "2026-10-31", "total": 980},
        {"day": "2026-11-01", "total": 450},
    ],
    "expenses": [
        {"id": 1, "day": "2026-11-02", "amount": 350, "category": "food", "description": "dinner"},
        {"id": 2, "day": "2026-11-01", "amount": 85.5, "category": "coffee", "description": "latte"},
    ],
}
WATER = {"ok": True, "ml": 1500, "goal_ml": 2000}


def show(**kw) -> ShowArgs:
    return ShowArgs.model_validate({"source": "spending.summary", **kw})


# ---- values ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, fmt, said",
    [
        (1820, Format.MONEY, "NT$1,820"),
        (-85, Format.MONEY, "-NT$85"),
        (1234.567, Format.NUMBER, "1,234.57"),
        (0.75, Format.PERCENT, "75%"),
        (82.5, Format.PERCENT, "82.5%"),
        ("2026-11-02", Format.DATE, "Nov 2"),
        ("2025-12-31", Format.DATE, "Dec 31, 2025"),
        ("2026-11-02T06:05:00Z", Format.DATE, "Nov 2 14:05"),  # in Main's zone
        (True, Format.BOOL, "yes"),
        (None, Format.NUMBER, "—"),
        (["a", "b"], Format.TEXT, "a, b"),
    ],
)
def test_a_value_reads_one_way_on_every_channel(value, fmt, said):
    assert FMT.cell(value, fmt).s == said


def test_money_in_another_currency_keeps_its_cents():
    usd = Formatter(currency="USD")
    assert [usd.cell(v, Format.MONEY).s for v in (12.5, 12, 1200)] == ["$12.50", "$12", "$1,200"]
    assert Formatter(currency="CHF").cell(3, Format.MONEY).s == "CHF 3"


def test_auto_reads_the_values_and_an_amounts_key():
    assert FMT.resolve(Format.AUTO, [350, 85.5], "amount") == Format.MONEY
    assert FMT.resolve(Format.AUTO, [3, 4], "count") == Format.NUMBER
    assert FMT.resolve(Format.AUTO, ["2026-11-02", "2026-11-01"], "day") == Format.DATE
    assert FMT.resolve(Format.AUTO, ["food", 3], "x") == Format.TEXT
    assert FMT.resolve(Format.AUTO, [True, False], "done") == Format.BOOL


# ---- the blocks --------------------------------------------------------------------------------------------


def test_a_table_of_entries():
    block = build(show(kind="table", source="spending.history", path="expenses", title="This week"), SPENDING, FMT)
    assert isinstance(block, TableBlock) and block.total == 2
    assert [(c.key, c.label, c.format) for c in block.columns] == [
        ("id", "Id", Format.NUMBER),
        ("day", "Day", Format.DATE),
        ("amount", "Amount", Format.MONEY),
        ("category", "Category", Format.TEXT),
        ("description", "Description", Format.TEXT),
    ]
    assert [c.s for c in block.rows[1]] == ["2", "Nov 1", "NT$86", "coffee", "latte"]  # TWD has no cents
    assert block.rows[1][2].v == 85.5  # sorted and plotted by the value, not by the text
    assert block.text.splitlines()[:3] == [
        "Id  Day    Amount  Category  Description",
        "──  ─────  ──────  ────────  ───────────",
        " 1  Nov 2  NT$350  food      dinner",
    ]


def test_a_table_shows_the_fields_asked_for_in_their_order_and_names():
    args = show(
        kind="table",
        path="expenses",
        fields=[{"key": "description", "label": "What"}, {"key": "amount", "format": "money"}],
    )
    block = build(args, SPENDING, FMT)
    assert [c.label for c in block.columns] == ["What", "Amount"] and block.rows[0][0].s == "dinner"
    with pytest.raises(ShowError, match="no field 'price'.*its fields: id, day, amount"):
        build(show(kind="table", path="expenses", fields=[{"key": "price"}]), SPENDING, FMT)


def test_a_map_is_a_table_of_names_and_values_whatever_show_calls_them():
    block = build(show(kind="table", path="by_category"), SPENDING, FMT)
    assert [c.label for c in block.columns] == ["Category", "Value"]
    named = show(kind="table", path="by_category", fields=[{"key": "cat"}, {"key": "spent", "format": "money"}])
    block = build(named, SPENDING, FMT)
    assert [c.label for c in block.columns] == ["Cat", "Spent"] and block.rows[0][1].s == "NT$740"


def test_a_long_table_keeps_its_first_rows_and_says_how_many_there_were():
    many = {"rows": [{"n": i} for i in range(MAX_ROWS + 30)]}
    block = build(show(kind="table", path="rows"), many, FMT)
    assert len(block.rows) == MAX_ROWS and block.total == MAX_ROWS + 30
    assert block.text.endswith(f"… {MAX_ROWS + 30 - 15} more")


def test_a_bar_chart_ranks_its_bars_largest_first():
    block = build(show(kind="chart", path="by_category", title="By category"), SPENDING, FMT)
    assert isinstance(block, ChartBlock) and block.chart == "bar"
    assert [p.x.s for p in block.points] == ["food", "coffee", "transport", "other"]
    assert block.series[0].format == Format.NUMBER  # a map's values: no key says money
    money = build(
        show(kind="chart", path="by_category", fields=[{"key": "c"}, {"key": "spent", "format": "money"}]),
        SPENDING,
        FMT,
    )
    assert (money.series[0].prefix, money.points[0].y[0].s) == ("NT$", "NT$1,820")
    assert money.text.splitlines()[0] == "food       ████████████████  NT$1,820"


def test_a_bar_chart_of_many_names_keeps_the_largest():
    data = {"by": {f"n{i}": i for i in range(30)}}
    block = build(show(kind="chart", path="by"), data, FMT)
    assert len(block.points) == MAX_BARS and block.total == 30 and block.points[0].x.s == "n29"


def test_a_line_over_time_is_in_date_order():
    block = build(show(kind="chart", chart="line", path="by_day"), SPENDING, FMT)
    assert (block.x.key, block.x.format, block.series[0].key) == ("day", Format.DATE, "total")
    assert [p.x.s for p in block.points] == ["Oct 31", "Nov 1", "Nov 2"]
    assert block.text.splitlines() == ["Oct 31 → Nov 2", "Total  █▁▆  last NT$820, high NT$980"]


@pytest.mark.parametrize(
    "args, error",
    [
        (
            {"path": "expenses", "fields": [{"key": "day"}, {"key": "category"}]},
            "series are numbers; not these: category",
        ),
        ({"path": "by_day", "fields": [{"key": "day"}] + [{"key": "total"}] * 5}, "at most 4 series"),
        ({"path": "by_day", "fields": [{"key": "day"}]}, "a name or date field, then one to four"),
        ({"path": "nowhere"}, "no 'nowhere' in the reply of spending.summary; its fields: total, count"),
        ({"path": "total"}, "not a list of entries"),
    ],
)
def test_a_chart_that_cannot_be_drawn_says_why(args, error):
    with pytest.raises(ShowError, match=error):
        build(show(kind="chart", **args), SPENDING, FMT)


def test_stats_are_the_numbers_of_one_record():
    block = build(show(kind="stats", title="This week"), SPENDING, FMT)
    assert isinstance(block, StatsBlock)
    assert [(f.label, f.value.s) for f in block.stats] == [("Total", "NT$3,420"), ("Count", "6")]
    assert block.text == "Total  NT$3,420\nCount  6"


def test_details_label_every_field_of_one_record():
    block = build(show(kind="details", source="spending.history", path="expenses.0"), SPENDING, FMT)
    assert isinstance(block, DetailsBlock)
    assert [(f.label, f.value.s) for f in block.items][:3] == [("Id", "1"), ("Day", "Nov 2"), ("Amount", "NT$350")]


def test_a_meter_against_the_goal_in_the_data_or_the_one_given():
    args = show(kind="meter", source="water.today", fields=[{"key": "ml", "label": "Water"}, {"key": "goal_ml"}])
    block = build(args, WATER, FMT)
    assert isinstance(block, MeterBlock) and (block.label, block.value.s, block.max.s) == ("Water", "1,500", "2,000")
    assert block.text == "Water  ▓▓▓▓▓▓▓▓░░  1,500 / 2,000 (75%)"
    given = build(show(kind="meter", source="water.today", fields=[{"key": "ml"}], goal=3000), WATER, FMT)
    assert given.max.s == "3,000"
    with pytest.raises(ShowError, match="needs a goal"):
        build(show(kind="meter", source="water.today", fields=[{"key": "ml"}]), WATER, FMT)
    with pytest.raises(ShowError, match="above zero"):
        build(show(kind="meter", source="water.today", fields=[{"key": "ml"}], goal=0), WATER, FMT)


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
