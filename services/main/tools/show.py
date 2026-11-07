"""`show`: a module's data under the reply, as a table, a chart, stats, details or a meter (blocks.py).

It draws only on what a module answered in this turn (ask_module keeps each reply on the turn), so every number on
screen is the module's, never one the model wrote. The block goes out with the reply; the planner is told what it
showed, so it says what it means instead of writing it out again.
"""

from __future__ import annotations

from typing import Any

from ..blocks import MAX_BLOCKS, ShowArgs, ShowError, build, summary
from .base import Tool, ToolContext


async def show(args: ShowArgs, ctx: ToolContext) -> dict[str, Any]:
    turn = ctx.turn
    source = args.source.strip().removeprefix("rpc.mod.")
    reply = turn.replies.get(source)
    if reply is None:
        asked = ", ".join(turn.replies) or "none yet"
        return {
            "ok": False,
            "error": f"no reply from {source} in this turn: call ask_module for it first (asked so far: {asked})",
        }
    if len(turn.blocks) >= MAX_BLOCKS:
        return {"ok": False, "error": f"{MAX_BLOCKS} blocks are shown already: that is enough for one reply"}
    try:
        block = build(args, reply, turn.formatter)
    except ShowError as e:
        return {"ok": False, "error": str(e)}
    turn.blocks.append(block)
    return {"ok": True, "shown": summary(block)}


SHOW = Tool(
    name="show",
    description=(
        "Put a module's data on screen under your reply: a table, a chart, stats, details or a meter, made from "
        "the reply of a request you called with ask_module in this turn. Then say in a line or two what it means; "
        "do not write out again what it shows."
    ),
    args=ShowArgs,
    handler=show,
)
