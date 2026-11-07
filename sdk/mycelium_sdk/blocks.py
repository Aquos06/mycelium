"""A module's data as a block: a table, a chart, stats, details or a meter. Main shows one under a reply (`show`),
a module page shows its views (views.py), and both build them here, from the module's own reply.

A BlockSpec says how to see the data: which kind, where in the reply (`path`), which fields, a title. `build` turns
a reply into the block, or raises BlockError with what does not fit, in words a model can act on. Each value goes
out twice, as data (`v`: to sort and to plot) and as it reads (`s`: "NT$350", "Nov 7"), so only this formats and
every reader says the same. `text` is the block in plain monospace lines, for a channel that shows only text.

    table    rows: a list of records, a map of name -> number (or -> record)
    chart    bar (amounts by a name, largest first; by a date, in order), line or area (over time); 1-4 series
    stats    a few headline numbers of one record
    details  one record, every field labelled
    meter    one number against a goal (a field of the record, or a goal given)
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime, tzinfo
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .text import cut

MAX_ROWS = 100  # a table's rows; `total` says how many the data had
MAX_BARS = 12  # a bar chart's bars, largest first
MAX_POINTS = 90  # a line's points, the latest kept
MAX_SERIES = 4  # a chart's series: the colours that stay apart for everyone
MAX_FIGURES = 6  # stats; details take MAX_DETAILS
MAX_DETAILS = 12
MAX_COLUMNS = 6  # a table's columns when `show` names none
MAX_AUTO = 4  # blocks made from one reply's shape (auto)
TEXT_ROWS = 15  # rows in a table's text: a phone shows no more
TEXT_MAX = 3500  # a block's text: one Telegram message, with its title
BAR_WIDTH = 16  # characters of the longest bar in a chart's text
CELL_WIDTH = 24  # characters of a cell in a table's text

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
CURRENCIES = {  # symbol, decimals
    "TWD": ("NT$", 0),
    "USD": ("$", 2),
    "EUR": ("€", 2),
    "GBP": ("£", 2),
    "JPY": ("¥", 0),
    "CNY": ("CN¥", 2),
    "HKD": ("HK$", 2),
    "SGD": ("S$", 2),
    "IDR": ("Rp", 0),
    "KRW": ("₩", 0),
}


class Kind(StrEnum):
    TABLE = "table"
    CHART = "chart"
    STATS = "stats"
    DETAILS = "details"
    METER = "meter"


class ChartType(StrEnum):
    BAR = "bar"
    LINE = "line"
    AREA = "area"


class Format(StrEnum):
    AUTO = "auto"  # what the values look like
    TEXT = "text"
    NUMBER = "number"
    MONEY = "money"
    PERCENT = "percent"
    DATE = "date"
    BOOL = "bool"


NUMERIC = {Format.NUMBER, Format.MONEY, Format.PERCENT}


class BlockError(ValueError):
    """The data cannot be shown that way; the message says why, in words a model can act on."""


# ---- the blocks, as they go out ---------------------------------------------------------------------------


class Cell(BaseModel):
    v: float | str | bool | None = None  # the value: a number, an ISO date, text; a percent in points (75 for 75%)
    s: str = ""  # as it reads


class Column(BaseModel):
    key: str
    label: str
    format: Format  # never auto
    prefix: str = ""  # an axis tick's: "NT$" for money
    suffix: str = ""  # "%" for a percent

    @property
    def numeric(self) -> bool:
        return self.format in NUMERIC


class Figure(BaseModel):
    """One labelled value: a stat, a detail."""

    label: str
    value: Cell


class Point(BaseModel):
    x: Cell
    y: list[Cell]  # one per series


class TableBlock(BaseModel):
    kind: Literal[Kind.TABLE] = Kind.TABLE
    title: str = ""
    columns: list[Column]
    rows: list[list[Cell]]  # a cell per column
    total: int  # rows in the data; `rows` holds at most MAX_ROWS
    text: str = ""


class ChartBlock(BaseModel):
    kind: Literal[Kind.CHART] = Kind.CHART
    chart: ChartType
    title: str = ""
    x: Column
    series: list[Column] = Field(min_length=1, max_length=MAX_SERIES)
    points: list[Point]
    total: int  # points in the data; a bar chart keeps the largest MAX_BARS, a line the latest MAX_POINTS
    text: str = ""


class StatsBlock(BaseModel):
    kind: Literal[Kind.STATS] = Kind.STATS
    title: str = ""
    stats: list[Figure] = Field(min_length=1, max_length=MAX_FIGURES)
    text: str = ""


class DetailsBlock(BaseModel):
    kind: Literal[Kind.DETAILS] = Kind.DETAILS
    title: str = ""
    items: list[Figure] = Field(min_length=1, max_length=MAX_DETAILS)
    text: str = ""


class MeterBlock(BaseModel):
    kind: Literal[Kind.METER] = Kind.METER
    title: str = ""
    label: str
    value: Cell
    max: Cell
    text: str = ""


Block = Annotated[TableBlock | ChartBlock | StatsBlock | DetailsBlock | MeterBlock, Field(discriminator="kind")]


# ---- what `show` asks for ---------------------------------------------------------------------------------


class FieldArg(BaseModel):
    key: str = Field(min_length=1, max_length=80, description="the field in the data, as the module's reply names it")
    label: str = Field(default="", max_length=40, description="how it reads; the key when empty")
    format: Format = Field(
        default=Format.AUTO, description="money for amounts, percent, date, number, text, bool; auto guesses"
    )

    @model_validator(mode="before")
    @classmethod
    def _bare_key(cls, data: Any) -> Any:
        """`amount` for `{key: amount}`: how a manifest writes most fields."""
        return {"key": data} if isinstance(data, str) else data


class BlockSpec(BaseModel):
    """How to see a module's reply: the kind of block, where in the reply its data is, which fields, a title."""

    kind: Kind = Field(
        description=(
            "table: a list of entries · chart: numbers by a name or over time · stats: a few headline numbers · "
            "details: one record · meter: one number against a goal"
        )
    )
    path: str = Field(
        default="",
        max_length=120,
        description="where the data is in the reply, as dotted keys: expenses, by_category; empty for the whole reply",
    )
    title: str = Field(default="", max_length=80, description="a short title")
    fields: list[FieldArg] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "table: its columns, in order · chart: the name or date field first, then 1 to 4 number fields · "
            "stats, details: the values to show · meter: the value, then the goal's field if the data has one. "
            "Empty: the data's own fields"
        ),
    )
    chart: ChartType = Field(
        default=ChartType.BAR, description="chart only: bar for amounts by name, line or area for over time"
    )
    goal: float | None = Field(default=None, description="meter only: the goal when the data has none (2000 for 2 l)")

    @model_validator(mode="before")
    @classmethod
    def _show(cls, data: Any) -> Any:
        """`show: table` for `kind: table`: how a manifest's view reads."""
        if isinstance(data, dict) and "show" in data and "kind" not in data:
            return {**{k: v for k, v in data.items() if k != "show"}, "kind": data["show"]}
        return data


# ---- formatting --------------------------------------------------------------------------------------------


class Formatter(BaseModel):
    """How Main writes a value: its currency for money, its zone for times."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    currency: str = "TWD"
    zone: tzinfo | None = None
    today: date | None = None  # a date this year reads without its year
    money: bool = False  # the data speaks of money (money_around): a `total` in it is money too

    def resolve(self, fmt: Format, values: list[Any], key: str = "") -> Format:
        """`auto`, from the values (all numbers: number; all ISO dates: date; ...) and, for money, the key."""
        if fmt != Format.AUTO:
            return fmt
        present = [v for v in values if v is not None and v != ""]
        if not present:
            return Format.TEXT
        if all(isinstance(v, bool) for v in present):
            return Format.BOOL
        if all(_number(v) is not None and not isinstance(v, bool) for v in present):
            return Format.MONEY if _moneyish(key, self.money) else Format.NUMBER
        if all(isinstance(v, str) and (ISO_DATE.match(v) or ISO_TIME.match(v)) for v in present):
            return Format.DATE
        return Format.TEXT

    def affix(self, fmt: Format) -> tuple[str, str]:
        if fmt == Format.MONEY:
            symbol, _ = CURRENCIES.get(self.currency.upper(), (f"{self.currency} ", 2))
            return symbol, ""
        return ("", "%") if fmt == Format.PERCENT else ("", "")

    def cell(self, value: Any, fmt: Format) -> Cell:
        if value is None or value == "":
            return Cell(v=None, s="—")
        match fmt:
            case Format.NUMBER | Format.MONEY | Format.PERCENT:
                n = _number(value)
                if n is None:
                    return Cell(v=str(value), s=str(value))
                if fmt == Format.PERCENT:
                    n = n * 100 if abs(n) <= 1 else n  # 0.75 and 75 are both 75%
                    return Cell(v=n, s=f"{_digits(n, 1)}%")
                if fmt == Format.MONEY:
                    symbol, decimals = CURRENCIES.get(self.currency.upper(), (f"{self.currency} ", 2))
                    sign = "-" if n < 0 else ""
                    return Cell(v=n, s=f"{sign}{symbol}{_digits(abs(n), decimals, keep=decimals > 0 and n % 1 != 0)}")
                return Cell(v=n, s=_digits(n, 2))
            case Format.DATE:
                return Cell(v=str(value), s=self.when(str(value)))
            case Format.BOOL:
                yes = value if isinstance(value, bool) else str(value).lower() in ("true", "yes", "1")
                return Cell(v=bool(yes), s="yes" if yes else "no")
            case _:
                return Cell(v=_plain(value), s=_plain(value))

    def when(self, iso: str) -> str:
        """ "Nov 7", "Nov 7, 2025", "Nov 7 14:05": a date, or a time in Main's zone."""
        try:
            if ISO_DATE.match(iso):
                d, clock = date.fromisoformat(iso), ""
            else:
                t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                if t.tzinfo and self.zone:
                    t = t.astimezone(self.zone)
                d, clock = t.date(), f" {t:%H:%M}"
        except ValueError:
            return iso
        year = "" if self.today is None or d.year == self.today.year else f", {d.year}"
        return f"{d:%b} {d.day}{year}{clock}"


def _number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        try:
            n = float(v.replace(",", "").strip())
        except ValueError:
            return None
        return n if math.isfinite(n) else None
    return None


MONEY = re.compile(r"(amount|cost|price|spent|spend|paid|balance|fee|income|budget|revenue|salary|expense|currency)")
SUM = re.compile(r"(total|sum|subtotal)")


def _moneyish(key: str, money_around: bool) -> bool:
    """`amount`, `price`: money. `total`: money only where the data speaks of money (an `amount` beside it, a
    `currency`): hello's total is a count of messages."""
    k = key.lower()
    return bool(MONEY.search(k)) or (money_around and bool(SUM.search(k)))


def money_around(data: Any) -> bool:
    """Whether a reply speaks of money anywhere: one of its keys, or a key of the first rows of a list in it."""
    keys: list[str] = []
    if isinstance(data, Mapping):
        keys += [str(k) for k in data]
        for v in data.values():
            if isinstance(v, list):
                keys += [str(k) for r in v[:3] if isinstance(r, Mapping) for k in r]
    return any(MONEY.search(k.lower()) for k in keys)


def _digits(n: float, decimals: int, keep: bool = False) -> str:
    """1234.5 -> "1,234.5"; trailing zeros dropped unless `keep` (money with cents keeps both)."""
    text = f"{n:,.{decimals}f}"
    if decimals and not keep:
        text = text.rstrip("0").rstrip(".")
    return text


def _plain(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(_plain(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_plain(x)}" for k, x in v.items())
    return str(v)


def _label(key: str) -> str:
    """`by_category` -> "Category", `total_ml` -> "Total ml"."""
    words = key.split(".")[-1].removeprefix("by_").replace("_", " ").replace("-", " ").strip()
    return (words[:1].upper() + words[1:]) or key


def _get(data: Any, path: str) -> Any:
    """`a.b.0.c` into dicts and lists."""
    at = data
    for part in [p for p in path.split(".") if p]:
        if isinstance(at, Mapping) and part in at:
            at = at[part]
        elif isinstance(at, list) and part.isdigit() and int(part) < len(at):
            at = at[int(part)]
        else:
            raise KeyError(part)
    return at


# ---- data -> rows, a record ------------------------------------------------------------------------------


def _rows(data: Any, names: tuple[str, str]) -> list[dict[str, Any]]:
    """A list of records; a list of values (one field, `value`); a map of name -> value or -> record, as rows with
    the name under names[0] and a value under names[1]."""
    if isinstance(data, list):
        if not data:
            return []
        if all(isinstance(r, Mapping) for r in data):
            return [dict(r) for r in data]
        return [{names[1]: r} for r in data]
    if isinstance(data, Mapping) and data:
        if all(isinstance(v, Mapping) for v in data.values()):
            return [{names[0]: k, **v} for k, v in data.items()]
        return [{names[0]: k, names[1]: v} for k, v in data.items()]
    raise BlockError("that data is not a list of entries or a map of names to values")


def _record(data: Any) -> dict[str, Any]:
    if isinstance(data, Mapping):
        return {k: v for k, v in data.items() if k != "ok"}
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], Mapping):
        return dict(data[0])
    raise BlockError("that data is not one record (an object of named values)")


def _value(row: Mapping[str, Any], key: str) -> Any:
    try:
        return _get(row, key)
    except KeyError:
        return None


def _keys(rows: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for r in rows[:50]:
        for k, v in r.items():
            if not isinstance(v, Mapping | list):
                seen.setdefault(k, None)
    return list(seen)


def _fields(asked: list[FieldArg], keys: list[str], names: tuple[str, str] | None = None) -> list[FieldArg]:
    """The fields `show` named, matched to the data; a map's two (its name, its value) take the first two names
    given, whatever they are called. None named: the data's own."""
    if not asked:
        return [FieldArg(key=k) for k in keys]
    out = []
    for i, f in enumerate(asked):
        if f.key in keys or "." in f.key:
            out.append(f)
        elif names is not None and i < 2:
            out.append(f.model_copy(update={"key": names[i], "label": f.label or _label(f.key)}))
        else:
            raise BlockError(f"no field {f.key!r} in that data; its fields: {', '.join(keys) or 'none'}")
    return out


# ---- building a block -------------------------------------------------------------------------------------


def build(
    args: BlockSpec, reply: Mapping[str, Any], fmt: Formatter, source: str = "the module"
) -> TableBlock | ChartBlock | StatsBlock | DetailsBlock | MeterBlock:
    """The block `args` asks for, from `reply` (the answer of `source`, a module's request: expenses.summary).
    BlockError when the data does not fit it."""
    fmt = fmt.model_copy(update={"money": money_around(reply)})
    try:
        data = _get({k: v for k, v in reply.items() if k != "ok"}, args.path)
    except KeyError as e:
        fields = ", ".join(k for k in reply if k != "ok") or "none"
        raise BlockError(f"no {e.args[0]!r} in the reply of {source}; its fields: {fields}") from None
    title = args.title.strip()
    match args.kind:
        case Kind.TABLE:
            block = _table(args, data, fmt, title)
        case Kind.CHART:
            block = _chart(args, data, fmt, title)
        case Kind.STATS:
            block = _figures(args, data, fmt, title, stats=True)
        case Kind.DETAILS:
            block = _figures(args, data, fmt, title, stats=False)
        case _:
            block = _meter(args, data, fmt, title)
    return block.model_copy(update={"text": text_of(block)})


def _column(f: FieldArg, rows: list[dict[str, Any]], fmt: Formatter) -> Column:
    resolved = fmt.resolve(f.format, [_value(r, f.key) for r in rows], f.key)
    prefix, suffix = fmt.affix(resolved)
    return Column(key=f.key, label=f.label or _label(f.key), format=resolved, prefix=prefix, suffix=suffix)


def _names(args: BlockSpec, data: Any) -> tuple[str, str]:
    """What a map's two columns are called: its path's name ("category" for by_category), and "value"."""
    base = args.path.split(".")[-1].removeprefix("by_") if args.path and isinstance(data, Mapping) else ""
    return base or "name", "value"


def _table(args: BlockSpec, data: Any, fmt: Formatter, title: str) -> TableBlock:
    names = _names(args, data)
    rows = _rows(data, names)
    keys = _keys(rows)
    fields = _fields(args.fields, keys, names if isinstance(data, Mapping) else None)
    if not args.fields:
        fields = fields[:MAX_COLUMNS]
    if not fields:
        raise BlockError("that data has no fields to show")
    columns = [_column(f, rows, fmt) for f in fields]
    cells = [[fmt.cell(_value(r, c.key), c.format) for c in columns] for r in rows[:MAX_ROWS]]
    return TableBlock(title=title, columns=columns, rows=cells, total=len(rows))


def _chart(args: BlockSpec, data: Any, fmt: Formatter, title: str) -> ChartBlock:
    names = _names(args, data)
    rows = _rows(data, names)
    if not rows:
        raise BlockError("that data is empty: nothing to chart")
    keys = _keys(rows)
    if args.fields:
        fields = _fields(args.fields, keys, names if isinstance(data, Mapping) else None)
    else:  # the first field that is not a number names each point; the first number is the series
        numbers = [k for k in keys if all(_number(_value(r, k)) is not None for r in rows if _value(r, k) is not None)]
        labels = [k for k in keys if k not in numbers]
        if not numbers:
            raise BlockError("that data has no numbers to chart")
        fields = [FieldArg(key=(labels or [names[0]])[0]), FieldArg(key=numbers[0])]
    if len(fields) < 2:
        raise BlockError("a chart needs a name or date field, then one to four number fields")
    if len(fields) > MAX_SERIES + 1:
        raise BlockError(f"a chart shows at most {MAX_SERIES} series: name fewer number fields")
    x = _column(fields[0], rows, fmt)
    series = [_column(f, rows, fmt) for f in fields[1:]]
    if not all(s.numeric for s in series):
        bad = ", ".join(s.key for s in series if not s.numeric)
        raise BlockError(f"a chart's series are numbers; not these: {bad}")
    over_time = x.format == Format.DATE  # a line by name keeps the data's order
    points = [
        Point(x=fmt.cell(_value(r, x.key), x.format), y=[fmt.cell(_value(r, s.key), s.format) for s in series])
        for r in rows
    ]
    total = len(points)
    if over_time:
        points.sort(key=lambda p: str(p.x.v))
    if args.chart == ChartType.BAR:
        if not over_time:  # ranked: the largest first
            points.sort(key=lambda p: -(p.y[0].v if isinstance(p.y[0].v, float) else -math.inf))
            points = points[:MAX_BARS]
        else:
            points = points[-MAX_BARS:]
    else:
        points = points[-MAX_POINTS:]
    return ChartBlock(chart=args.chart, title=title, x=x, series=series, points=points, total=total)


def _figures(args: BlockSpec, data: Any, fmt: Formatter, title: str, stats: bool) -> StatsBlock | DetailsBlock:
    record = _record(data)
    keys = [k for k, v in record.items() if not isinstance(v, Mapping | list)]
    if stats and not args.fields:
        keys = [k for k in keys if _number(record[k]) is not None]
    fields = _fields(args.fields, list(record) if args.fields else keys)
    limit = MAX_FIGURES if stats else MAX_DETAILS
    if not fields:
        raise BlockError("that record has no numbers to show as stats" if stats else "that record has no fields")
    figures = []
    for f in fields[:limit]:
        value = _value(record, f.key)
        resolved = fmt.resolve(f.format, [value], f.key)
        figures.append(Figure(label=f.label or _label(f.key), value=fmt.cell(value, resolved)))
    if stats:
        return StatsBlock(title=title, stats=figures)
    return DetailsBlock(title=title, items=figures)


def _meter(args: BlockSpec, data: Any, fmt: Formatter, title: str) -> MeterBlock:
    record = _record(data) if not isinstance(data, int | float) else {"value": data}
    if not args.fields and len(record) != 1:
        raise BlockError("a meter needs `fields`: the value, then the goal's field (or `goal`)")
    fields = _fields(args.fields, list(record)) if args.fields else [FieldArg(key=next(iter(record)))]
    value_field = fields[0]
    value = _number(_value(record, value_field.key))
    if value is None:
        raise BlockError(f"{value_field.key!r} is not a number")
    if len(fields) > 1:
        goal = _number(_value(record, fields[1].key))
        if goal is None:
            raise BlockError(f"{fields[1].key!r} is not a number")
    elif args.goal is not None:
        goal = args.goal
    else:
        raise BlockError("a meter needs a goal: a second field holding it, or `goal`")
    if goal <= 0:
        raise BlockError("a meter's goal is above zero")
    resolved = fmt.resolve(value_field.format, [value], value_field.key)
    return MeterBlock(
        title=title,
        label=value_field.label or _label(value_field.key),
        value=fmt.cell(value, resolved),
        max=fmt.cell(goal, resolved),
    )


def auto(
    reply: Mapping[str, Any], fmt: Formatter, name: str
) -> list[TableBlock | ChartBlock | StatsBlock | DetailsBlock | MeterBlock]:
    """Blocks from a reply's own shape, for a module that declares no views: its numbers as stats (a record without
    numbers as details), each map of numbers as bars, each list as a table. `name` titles the overview."""
    data = {k: v for k, v in reply.items() if k != "ok"}
    specs: list[BlockSpec] = []
    numbers = [k for k, v in data.items() if not isinstance(v, bool) and _number(v) is not None]
    scalars = [k for k, v in data.items() if not isinstance(v, Mapping | list)]
    if numbers:
        specs.append(
            BlockSpec(kind=Kind.STATS, title=_title(name), fields=[FieldArg(key=k) for k in numbers[:MAX_FIGURES]])
        )
    elif scalars:
        specs.append(
            BlockSpec(kind=Kind.DETAILS, title=_title(name), fields=[FieldArg(key=k) for k in scalars[:MAX_DETAILS]])
        )
    for k, v in data.items():
        if isinstance(v, Mapping) and v and all(not isinstance(x, bool) and _number(x) is not None for x in v.values()):
            specs.append(BlockSpec(kind=Kind.CHART, title=_title(k), path=k))
        elif isinstance(v, list) and v:
            specs.append(BlockSpec(kind=Kind.TABLE, title=_title(k), path=k))
    out = []
    for spec in specs[:MAX_AUTO]:
        try:
            out.append(build(spec, reply, fmt, name))
        except BlockError:
            continue
    return out


def _title(name: str) -> str:
    """`by_category` -> "By category", `history` -> "History"."""
    text = name.replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:]


def summary(block: TableBlock | ChartBlock | StatsBlock | DetailsBlock | MeterBlock) -> str:
    """What the planner is told it showed, so it does not write it out again."""
    match block:
        case TableBlock():
            more = f" (the first {len(block.rows)})" if block.total > len(block.rows) else ""
            return f"a table of {block.total} rows{more}: {', '.join(c.label for c in block.columns)}"
        case ChartBlock():
            return f"a {block.chart} chart of {', '.join(s.label for s in block.series)} by {block.x.label}, {len(block.points)} points"
        case StatsBlock():
            return "stats: " + ", ".join(f"{f.label} {f.value.s}" for f in block.stats)
        case DetailsBlock():
            return f"the details of one record: {', '.join(f.label for f in block.items)}"
        case _:
            return f"a meter: {block.label} {block.value.s} of {block.max.s}"


# ---- as text ------------------------------------------------------------------------------------------------


def text_of(block: TableBlock | ChartBlock | StatsBlock | DetailsBlock | MeterBlock) -> str:
    """The block in monospace lines."""
    match block:
        case TableBlock():
            lines = _grid(
                [c.label for c in block.columns],
                [[c.s for c in r] for r in block.rows[:TEXT_ROWS]],
                [c.numeric for c in block.columns],
            )
            if block.total > TEXT_ROWS:
                lines.append(f"… {block.total - TEXT_ROWS} more")
        case ChartBlock() if block.chart == ChartType.BAR:
            lines = _bars(block)
        case ChartBlock():
            lines = _sparks(block)
        case StatsBlock():
            lines = _pairs([(f.label, f.value.s) for f in block.stats])
        case DetailsBlock():
            lines = _pairs([(f.label, f.value.s) for f in block.items])
        case _:
            v, m = block.value.v, block.max.v
            ratio = v / m if isinstance(v, float) and isinstance(m, float) and m else 0.0
            filled = max(0, min(10, round(ratio * 10)))
            lines = [
                f"{block.label}  {'▓' * filled}{'░' * (10 - filled)}  {block.value.s} / {block.max.s} ({round(ratio * 100)}%)"
            ]
    return cut("\n".join(lines), TEXT_MAX)


def _grid(head: list[str], rows: list[list[str]], right: list[bool]) -> list[str]:
    cells = [[cut(c, CELL_WIDTH) for c in r] for r in [head, *rows]]
    widths = [max(len(r[i]) for r in cells) for i in range(len(head))]

    def line(r: list[str]) -> str:
        return "  ".join(
            c.rjust(w) if right[i] else c.ljust(w) for i, (c, w) in enumerate(zip(r, widths, strict=True))
        ).rstrip()

    return [line(cells[0]), "  ".join("─" * w for w in widths), *(line(r) for r in cells[1:])]


def _pairs(pairs: list[tuple[str, str]]) -> list[str]:
    width = max(len(k) for k, _ in pairs)
    return [f"{k.ljust(width)}  {v}" for k, v in pairs]


def _bars(block: ChartBlock) -> list[str]:
    values = [p.y[0].v if isinstance(p.y[0].v, float) else 0.0 for p in block.points]
    top = max((abs(v) for v in values), default=0.0) or 1.0
    names = [cut(p.x.s, 14) for p in block.points]
    width = max((len(n) for n in names), default=0)
    lines = []
    for p, n, v in zip(block.points, names, values, strict=True):
        bar = "█" * max(1 if v else 0, round(abs(v) / top * BAR_WIDTH))
        rest = " · ".join(c.s for c in p.y[1:])
        lines.append(f"{n.ljust(width)}  {bar.ljust(BAR_WIDTH)}  {p.y[0].s}{f' · {rest}' if rest else ''}")
    if len(block.series) > 1:
        lines.append(" · ".join(s.label for s in block.series))
    if block.total > len(block.points):
        lines.append(f"(the largest {len(block.points)} of {block.total})")
    return lines


SPARK = "▁▂▃▄▅▆▇█"


def _sparks(block: ChartBlock) -> list[str]:
    first, last = block.points[0].x.s, block.points[-1].x.s
    lines = [f"{first} → {last}"]
    for i, s in enumerate(block.series):
        cells = [p.y[i] for p in block.points]
        values = [c.v if isinstance(c.v, float) else None for c in cells]
        known = [v for v in values if v is not None]
        if not known:
            continue
        lo, hi = min(known), max(known)
        spark = "".join(
            " " if v is None else SPARK[0 if hi == lo else round((v - lo) / (hi - lo) * (len(SPARK) - 1))]
            for v in values
        )
        high = cells[values.index(hi)].s
        lines.append(f"{s.label}  {spark[-40:]}  last {cells[-1].s}, high {high}")
    return lines
