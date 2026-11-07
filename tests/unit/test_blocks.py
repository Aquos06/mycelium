"""A module's data as a block (mycelium_sdk.blocks): how each value reads, each kind of block from a reply, what
does not fit and why, and blocks made from a reply's own shape for a module without views."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from mycelium_sdk.blocks import (
    MAX_BARS,
    MAX_ROWS,
    BlockError,
    BlockSpec,
    ChartBlock,
    DetailsBlock,
    Format,
    Formatter,
    MeterBlock,
    StatsBlock,
    TableBlock,
    auto,
)
from mycelium_sdk.blocks import build as build_block

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
ShowError = BlockError


def show(source: str = "spending.summary", **kw) -> tuple[BlockSpec, str]:
    return BlockSpec.model_validate(kw), source


def build(spec_source: tuple[BlockSpec, str], reply, fmt):
    spec, source = spec_source
    return build_block(spec, reply, fmt, source)


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


def test_a_total_is_money_only_where_the_data_speaks_of_money():
    count = build(show(kind="stats", source="hello.stats"), {"ok": True, "count": 5, "total": 76}, FMT)
    assert [f.value.s for f in count.stats] == ["5", "76"]  # hello's messages, not dollars
    spent = build(show(kind="stats", fields=["total"]), {"ok": True, "total": 76, "currency": "TWD"}, FMT)
    assert spent.stats[0].value.s == "NT$76"
    assert build(show(kind="stats"), SPENDING, FMT).stats[0].value.s == "NT$3,420"  # its entries have an amount


def test_a_manifest_writes_a_field_as_its_key_and_the_kind_as_show():
    spec = BlockSpec.model_validate({"show": "table", "fields": ["day", {"key": "amount", "format": "money"}]})
    assert spec.kind == "table" and [(f.key, f.format) for f in spec.fields] == [("day", "auto"), ("amount", "money")]


# ---- blocks from a reply's own shape (a module without views) ------------------------------------------------


def test_a_reply_s_shape_makes_its_blocks():
    blocks = auto(SPENDING, FMT, "summary")
    assert [(b.kind, b.title) for b in blocks] == [
        ("stats", "Summary"),
        ("chart", "By category"),
        ("table", "By day"),
        ("table", "Expenses"),
    ]
    assert [(f.label, f.value.s) for f in blocks[0].stats] == [("Total", "NT$3,420"), ("Count", "6")]


def test_a_record_without_numbers_is_its_details_and_a_bare_list_a_table():
    (details,) = auto({"ok": True, "day": "2026-11-02", "position": "B1-03"}, FMT, "current")
    assert details.kind == "details" and details.text == "Day       Nov 2\nPosition  B1-03"
    (table,) = auto({"ok": True, "entries": [{"day": "2026-11-02", "position": "B1-03"}]}, FMT, "history")
    assert (table.kind, table.title, table.total) == ("table", "Entries", 1)
    assert auto({"ok": True, "items": []}, FMT, "list") == []  # nothing to show: no empty card
