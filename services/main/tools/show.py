"""`show`: a module's data under the reply, as a table, a chart, stats, details or a meter (mycelium_sdk.blocks).

By view (`spending.week`): Main asks the module for that view's data and builds the block the view describes. By
source: it draws on what a module answered in this turn (ask_module keeps each reply on the turn). Either way every
number on screen is the module's, never one the model wrote. The block goes out with the reply; the planner is told
what it showed, so it says what it means instead of writing it out again.

What the planner leaves out or gets wrong is filled in where only one answer fits, since each failed `show` costs a
round: the reply (a request named as a view, a module's name, or nothing: that module's only reply this turn, or
the turn's only one) and the path (left out, mistyped, or not where the fields are: the one place in the reply that
has them). A name that says something else (a request not asked yet, a view not listed) is never swapped for
another reply. When Main chose, the result says what it drew on (`from`), so the reply speaks of that.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mycelium_sdk.blocks import Block, BlockError, BlockSpec, Formatter, build, places, summary
from mycelium_sdk.views import View, resolve_args

from ..blocks import MAX_BLOCKS, ShowArgs, TurnData
from .base import Tool, ToolContext


async def show(args: ShowArgs, ctx: ToolContext) -> dict[str, Any]:
    turn = ctx.turn
    if len(turn.blocks) >= MAX_BLOCKS:
        return {"ok": False, "error": f"{MAX_BLOCKS} blocks are shown already: that is enough for one reply"}
    view = args.view.strip()
    module, _, view_id = view.partition(".")
    if view and (listed := (turn.views.get(module) or {}).get(view_id)):
        return await _view(view, listed, ctx)
    given = args.source.strip().removeprefix("rpc.mod.")
    name = given or view
    source, error = _source(name, as_view=not given, turn=turn)
    if source is None:
        return {"ok": False, "error": error}
    spec = args.spec()
    try:
        block, path = fit(spec, turn.replies[source], turn.formatter, source)
    except BlockError as e:
        return {"ok": False, "error": str(e)}
    turn.blocks.append(block)
    result: dict[str, Any] = {"ok": True, "shown": summary(block)}
    if source != name or path != spec.path:  # Main chose: the reply speaks of what it drew on
        result["from"] = source + (f", path {path}" if path else ", the whole reply" if spec.path else "")
    return result


def _source(name: str, as_view: bool, turn: TurnData) -> tuple[str | None, str]:
    """The reply `show` means, or why there is none: the one asked by that name; that module's only reply this turn
    when only a module is named, the turn's only reply when nothing is. Not guessed: a request not asked yet or a
    view not listed (another reply would be shown as if it were that one), or several replies that fit."""
    asked = ", ".join(turn.replies) or "none yet"
    if name in turn.replies:
        return name, ""
    module, _, action = name.partition(".")
    if not action:
        mine = [s for s in turn.replies if not module or s.partition(".")[0] == module]
        if len(mine) == 1:
            return mine[0], ""
        if mine:
            whose = f"from {module} " if module else ""
            return None, f"several replies {whose}this turn: name one as `source` ({', '.join(mine)})"
    if as_view and name:
        listed = ", ".join(f"{m}.{v}" for m, vs in turn.views.items() for v in vs) or "none"
        return None, (
            f"no view {name!r}; the views under Modules: {listed}. To show a reply you asked this turn, name it as "
            f"`source` (asked so far: {asked})"
        )
    if name:
        return None, f"no reply from {name} in this turn: call ask_module for it first (asked so far: {asked})"
    return None, (
        f"give a `view` listed under Modules, or a `source` you called with ask_module in this turn "
        f"(asked so far: {asked})"
    )


def fit(spec: BlockSpec, reply: Mapping[str, Any], fmt: Formatter, source: str) -> tuple[Block, str]:
    """The block and the path it came from: `path` when the data there fits; else the one place in the reply that
    fits, the best first (every field named there, then some of them, the rest taken by position as a map's two
    columns, then none: the reply's only place, by position), the reply itself first within a tier. So a path left
    out or mistyped (`total, count`, the source's name again) still finds its data. A table or a chart is never made
    of a reply's mixed top (totals beside lists). Places are ranked by their fields before any is built, and a tier
    is built only when the ones above fit nothing. BlockError naming the places and their fields when none or
    several fit."""
    where = places(reply, spec.kind)
    error = ""
    if spec.path or "" in where:
        try:
            return build(spec, reply, fmt, source), spec.path
        except BlockError as e:
            error = str(e)
    asked = {f.key for f in spec.fields}
    tiers: tuple[list[str], list[str], list[str]] = ([], [], [])
    for path, keys in where.items():
        if path == spec.path:
            continue  # tried
        found = len(asked & set(keys))
        if found == len(asked):
            tiers[0].append(path)
        elif found:
            tiers[1].append(path)
        elif len(where) == 1:
            tiers[2].append(path)
    listed = "; ".join(f"{p or '(the whole reply)'}: {', '.join(k)}" for p, k in where.items())
    for tier in tiers:
        built: dict[str, Block] = {}
        for path in tier:
            try:
                built[path] = build(spec.model_copy(update={"path": path}), reply, fmt, source)
            except BlockError:
                continue
        if "" in built:
            return built[""], ""
        if len(built) == 1:
            ((path, block),) = built.items()
            return block, path
        if built:
            lead = f"{error}; " if error else ""
            raise BlockError(f"{lead}that fits several places in the reply of {source}: name one as `path` ({listed})")
    if not error:
        empty = [k for k, v in reply.items() if k != "ok" and isinstance(v, Mapping | list) and not v]
        if not where and empty:
            are = "is" if len(empty) == 1 else "are"
            error = f"nothing in the reply of {source} to show: {', '.join(empty)} {are} empty"
        elif asked:
            error = f"no place in the reply of {source} fits a {spec.kind.value} of those fields"
        else:
            error = f"no place in the reply of {source} fits a {spec.kind.value}"
    raise BlockError(f"{error}. Where its data is, as `path`: {listed}" if listed else error)


async def _view(name: str, view: View, ctx: ToolContext) -> dict[str, Any]:
    turn = ctx.turn
    module = name.partition(".")[0]
    source = f"{module}.{view.request}"
    try:
        today = turn.formatter.today
        payload = resolve_args(view.args, today) if today else view.args
        reply = await ctx.bus.request(f"rpc.mod.{source}", payload, timeout=10.0)
    except Exception as e:
        return {"ok": False, "error": f"{source} did not answer: {type(e).__name__}: {e}"}
    if reply.get("ok") is False:
        return {"ok": False, "error": f"{source}: {reply.get('error') or 'refused'}"}
    turn.replies[source] = reply  # a later `show` by source may draw on it too
    try:
        block = build(view, reply, turn.formatter, source)
    except BlockError as e:
        return {"ok": False, "error": f"the view {name} does not fit what {source} answered: {e}"}
    turn.blocks.append(block)
    return {"ok": True, "shown": summary(block)}


SHOW = Tool(
    name="show",
    description=(
        "Put a module's data on screen under your reply: a table, a chart, stats, details or a meter. Name one of "
        "a module's views (listed under Modules) and Main gets its data; or point at the reply of a request you "
        "called with ask_module in this turn. Then say in a line or two what it means; do not write out again "
        "what it shows."
    ),
    args=ShowArgs,
    handler=show,
)
