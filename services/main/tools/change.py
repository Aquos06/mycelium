"""`change_module`: draft a change to a module the builder grew, for Hansen to approve.

Like `propose_module`: the planner says what should change, in Hansen's words; code checks that the module is
one the builder grew and is not being built now. A valid draft ends the turn, Main stores it as a proposal
(proposals.py, kind `change`) and sends a card with Change it / Not now. Only a tap starts the build
(rpc.build.start with `change`), in code. The module keeps running as it is, with its data, until the new
version passes its tests and deploys; a change that fails leaves it as it was.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .base import Tool, ToolContext
from .propose import CARD_LINES, Line, split_lines

SUMMARY_MAX = 200  # characters of the first line, as the Offered list shows the change


class ChangeArgs(BaseModel):
    module: str = Field(description="the module to change, as listed under Modules: one marked grown")
    change: list[Line] = Field(
        min_length=1,
        max_length=8,
        description=(
            "what it should do after the change, one line each: something to add, or what it does wrong and what "
            "is right. A request that should take or give something new, as `add {category: optional string}: "
            "store one expense with its category`"
        ),
    )
    why: str = Field(min_length=8, max_length=600, description="why Hansen wants it, close to his own words")

    @field_validator("module", mode="before")
    @classmethod
    def _slug(cls, v: Any) -> Any:
        return re.sub(r"[\s_]+", "-", v.strip().lower()) if isinstance(v, str) else v

    @field_validator("change", mode="before")
    @classmethod
    def _lines(cls, v: Any) -> Any:
        return split_lines(v)

    @property
    def name(self) -> str:
        """The module, under the name a proposal goes by."""
        return self.module

    def text(self) -> str:
        """The change as the builder takes it: the last section of the module's SPEC.md."""
        return "\n".join([f"Why: {self.why.strip()}", "", *(f"- {c}" for c in self.change)])

    def summary(self) -> str:
        first = self.change[0]
        return first if len(first) <= SUMMARY_MAX else first[:SUMMARY_MAX] + "…"

    def card(self, version: str | None = None) -> str:
        """What Hansen reads before he chooses."""
        shown = [f"- {c}" for c in self.change[:CARD_LINES]]
        if len(self.change) > CARD_LINES:
            shown.append(f"- and {len(self.change) - CARD_LINES} more")
        now = f" (now v{version})" if version else ""
        return "\n".join(
            [
                f"A change to {self.module}{now}:",
                *shown,
                "It keeps its data, and runs as it is until the new version passes its tests. "
                "Nothing changes until you choose.",
            ]
        )


async def _ask(ctx: ToolContext, subject: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        reply = await ctx.bus.request(subject, payload, timeout=2.0)
    except Exception:
        return None
    return reply if reply.get("ok", True) else None


async def change(args: ChangeArgs, ctx: ToolContext) -> dict[str, Any]:
    """Refused when the module is not one the builder grew, or is being built now; best effort, since the builder
    checks again at the tap: a supervisor that does not answer only means a refusal would come then."""
    listed, builds = await asyncio.gather(_ask(ctx, "rpc.sys.list", {}), _ask(ctx, "rpc.build.list", {"limit": 50}))
    if listed is None:
        return {"ok": True, "change": args.module}
    grown = {str(n) for n in listed.get("grown") or []}
    rows = {str(r.get("name")): r for r in listed.get("modules") or [] if r.get("name")}
    if args.module not in grown:
        if args.module in rows or args.module in (listed.get("folders") or []):
            error = f"{args.module} is hand-written, not grown: only modules marked grown can be changed. Tell Hansen."
        else:
            names = ", ".join(sorted(grown)) or "none"
            error = (
                f"there is no module {args.module!r} to change (grown: {names}). If Hansen wants a new one, call "
                "`propose_module`."
            )
        return {"ok": False, "error": error}
    for b in (builds or {}).get("builds") or []:
        if b.get("name") == args.module and b.get("status") in ("queued", "building"):
            return {
                "ok": False,
                "error": f"{args.module} is being built or changed right now: tell Hansen to ask again once it is done.",
            }
    row = rows.get(args.module) or {}
    version = row.get("version") or (row.get("manifest") or {}).get("version")
    return {"ok": True, "change": args.module, "version": version}


CHANGE_MODULE = Tool(
    name="change_module",
    description=(
        "Draft a change to a module marked grown, for Hansen to approve: when it does something wrong, misses "
        "something he wants, or should work differently. Say what it should do after the change, from his words. "
        "Ends your turn with a card (Change it / Not now); the module keeps its data and runs as it is until the "
        "new version is built."
    ),
    args=ChangeArgs,
    handler=change,
)
