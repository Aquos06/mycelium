"""`propose_module`: draft a module for Hansen to approve.

The planner fills the parts of a spec; code renders SPEC.md in the format of specs/expenses.md and checks
the name. Nothing is built here: a valid proposal ends the turn, Main stores it (proposals.py) and sends a
card with Build it / Not now. Only a tap on Build it starts the build, in code, without the model.
"""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, field_validator

from mycelium_sdk.manifest import NAME_RE, RESERVED

from .base import Tool, ToolContext

Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
REQUEST = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")  # a request name, as ask_module takes it
CARD_LINES = 6  # behaviour lines shown on the card; the spec keeps them all


class ProposeArgs(BaseModel):
    name: str = Field(description="the module's name: a lowercase slug, 2-31 characters (expenses, water-log)")
    purpose: str = Field(min_length=8, max_length=300, description="one sentence: what the module does")
    need: str = Field(min_length=8, max_length=600, description="why Hansen wants it, close to his own words")
    behaviour: list[Line] = Field(
        min_length=1,
        max_length=12,
        description=(
            "what it does, one line each: which chat messages it picks up and how it tells them apart, "
            "what it stores, when it speaks up, what it ignores"
        ),
    )
    answers: list[Line] = Field(
        default_factory=list,
        max_length=6,
        description="what you can ask it later, `request: what it returns`, e.g. `summary: totals for a date range`",
    )
    example: str | None = Field(default=None, max_length=300, description="a message it handles, as Hansen types it")

    @field_validator("name", mode="before")
    @classmethod
    def _slug(cls, v: Any) -> Any:
        """`Water Log` and `water_log` both mean water-log."""
        return re.sub(r"[\s_]+", "-", v.strip().lower()) if isinstance(v, str) else v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError("a lowercase slug of 2-31 letters, digits and dashes, starting with a letter")
        if v in RESERVED:
            raise ValueError(f"{v!r} is reserved; pick another name")
        return v

    @field_validator("behaviour", "answers", mode="before")
    @classmethod
    def _lines(cls, v: Any) -> Any:
        """A model that sends one block of text instead of a list still means one line per line."""
        if isinstance(v, str):
            return [s.strip().lstrip("-* ").strip() for s in v.splitlines() if s.strip()]
        return v

    def requests(self) -> list[tuple[str, str]]:
        """The answers as (request, what it returns); a line that names no request keeps its text."""
        out = []
        for a in self.answers:
            req, sep, what = a.partition(":")
            req = req.strip().strip("`").lower()
            out.append((req, what.strip()) if sep and REQUEST.match(req) else ("", a))
        return out

    def spec(self) -> str:
        """SPEC.md as the builder takes it (the format of specs/expenses.md)."""
        lines = [
            f"# Spec: {self.name}",
            "",
            f"**Observed need:** {self.need}",
            "",
            f"**What to build:** {self.purpose}",
        ]
        lines += [""] + [f"- {b}" for b in self.behaviour]
        lines += [f"- answers `{req}`: {what}" if req else f"- answers {what}" for req, what in self.requests()]
        if self.example:
            lines += ["", f'An example message: "{self.example}"']
        lines += ["", "No network, no actuation.", ""]
        return "\n".join(lines)

    def card(self) -> str:
        """What Hansen reads before he chooses."""
        shown = [f"- {b}" for b in self.behaviour[:CARD_LINES]]
        if len(self.behaviour) > CARD_LINES:
            shown.append(f"- and {len(self.behaviour) - CARD_LINES} more")
        asks = [req for req, _ in self.requests() if req]
        tail = [f"Then I can ask it: {', '.join(asks)}."] if asks else []
        return "\n".join(
            [f"A new module, {self.name}: {self.purpose}", *shown, *tail, "Nothing is built until you choose."]
        )


async def names_in_use(ctx: ToolContext) -> dict[str, str]:
    """Modules not retired, module folders and builds still running, by name: the names the builder refuses
    (services/builder/service.py `_known_modules`). Best effort: the builder checks again at start, so a lookup
    that fails here only means the refusal comes at the tap instead."""

    async def ask(subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await ctx.bus.request(subject, payload, timeout=2.0)
        except Exception:
            return {}

    listed, builds = await asyncio.gather(ask("rpc.sys.list", {}), ask("rpc.build.list", {"limit": 50}))
    taken: dict[str, str] = {}
    for row in listed.get("modules") or []:
        if (name := str(row.get("name") or "")) and row.get("status") != "retired":  # a retired name is free
            taken[name] = "a module with that name is deployed"
    for folder in listed.get("folders") or []:  # hand-written or grown, deployed or not: the name is used
        taken.setdefault(str(folder), "a module with that name exists, though it is not running")
    for b in builds.get("builds") or []:
        if b.get("status") in ("queued", "building") and (name := str(b.get("name") or "")):
            taken.setdefault(name, "a module with that name is being built")
    return taken


async def propose(args: ProposeArgs, ctx: ToolContext) -> dict[str, Any]:
    taken = await names_in_use(ctx)
    if args.name in taken:
        return {
            "ok": False,
            "error": f"{args.name!r}: {taken[args.name]}. If it does what Hansen wants, use it; else pick another name.",
        }
    return {"ok": True, "proposed": args.name, "spec": args.spec()}


PROPOSE_MODULE = Tool(
    name="propose_module",
    description=(
        "Draft a new module for Hansen to approve, when he wants something ongoing that no module does: "
        "tracking or logging things over time, counts, totals, history. Fill the spec from what he said. "
        "Ends your turn with a card (Build it / Not now); nothing is built unless he chooses Build it."
    ),
    args=ProposeArgs,
    handler=propose,
)
