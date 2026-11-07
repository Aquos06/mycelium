"""`show`: a module's data under the reply, as a table, a chart, stats, details or a meter (mycelium_sdk.blocks).

By view (`spending.week`): Main asks the module for that view's data and builds the block the view describes. By
source: it draws on what a module answered in this turn (ask_module keeps each reply on the turn). Either way every
number on screen is the module's, never one the model wrote. The block goes out with the reply; the planner is told
what it showed, so it says what it means instead of writing it out again.
"""

from __future__ import annotations

from typing import Any

from mycelium_sdk.blocks import BlockError, build, summary
from mycelium_sdk.views import resolve_args

from ..blocks import MAX_BLOCKS, ShowArgs
from .base import Tool, ToolContext


async def show(args: ShowArgs, ctx: ToolContext) -> dict[str, Any]:
    turn = ctx.turn
    if len(turn.blocks) >= MAX_BLOCKS:
        return {"ok": False, "error": f"{MAX_BLOCKS} blocks are shown already: that is enough for one reply"}
    if args.view:
        return await _view(args.view.strip(), ctx)
    source = args.source.strip().removeprefix("rpc.mod.")
    reply = turn.replies.get(source)
    if reply is None:
        asked = ", ".join(turn.replies) or "none yet"
        return {
            "ok": False,
            "error": f"no reply from {source} in this turn: call ask_module for it first (asked so far: {asked})",
        }
    try:
        block = build(args.spec(), reply, turn.formatter, source)
    except BlockError as e:
        return {"ok": False, "error": str(e)}
    turn.blocks.append(block)
    return {"ok": True, "shown": summary(block)}


async def _view(name: str, ctx: ToolContext) -> dict[str, Any]:
    turn = ctx.turn
    module, _, view_id = name.partition(".")
    views = turn.views.get(module) or {}
    view = views.get(view_id)
    if view is None:
        listed = ", ".join(f"{m}.{v}" for m, vs in turn.views.items() for v in vs) or "none"
        return {"ok": False, "error": f"no view {name!r}; the views under Modules: {listed}"}
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
