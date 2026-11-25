"""The memory tools: `remember` writes to the vault, `recall` opens more of it (rpc.memory.*)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from mycelium_sdk import NoteType  # the same list memory files notes by

from .base import Tool, ToolContext

# ---- remember --------------------------------------------------------------------------------------


class RememberArgs(BaseModel):
    note: str = Field(
        min_length=1,
        description="entity slug (mei, ramen-place-xinyi) or the note path the memory pack shows (people/mei.md)",
    )
    type: NoteType | None = Field(default=None, description="only used when the note is new")
    aliases: list[str] = Field(default_factory=list, description="other names, e.g. 小美")
    fact: str | None = Field(
        default=None,
        description="what happened or is true, one line, past tense, without the date: 'is moving to Tainan in December'",
    )
    day: date | None = Field(default=None, description="YYYY-MM-DD the fact is about; default today")
    summary: str | None = Field(default=None, description="replace the note's current-state paragraph")

    @field_validator("note")
    @classmethod
    def _slug(cls, v: str) -> str:
        """The slug, also when the planner hands back the path it saw in the pack (people/mei.md -> mei)."""
        v = v.strip().lower()
        if v.startswith("summaries/"):
            raise ValueError("a day summary is not a note; remember the person, place or thing it is about")
        v = v.removesuffix(".md").rsplit("/", 1)[-1]
        if not v:
            raise ValueError("note is required")
        return v

    @model_validator(mode="after")
    def _date_goes_in_day(self) -> RememberArgs:
        """'2026-10-23 moved to Tainan' -> day=2026-10-23, fact='moved to Tainan'; a day without a fact is a mistake."""
        if self.fact and (m := re.match(r"^(\d{4}-\d{2}-\d{2})\s+(.+)$", self.fact.strip())):
            self.fact = m.group(2)
            self.day = self.day or date.fromisoformat(m.group(1))
        if self.day is not None and not self.fact:
            raise ValueError("day only makes sense together with a fact")
        return self


class FactPayload(BaseModel):
    text: str
    day: date | None = None


class RememberPayload(BaseModel):
    """The rpc.memory.remember request as Main fills it (memory validates it again as RememberRequest)."""

    note: str
    source: str
    type: NoteType | None = None
    aliases: list[str] | None = None
    fact: FactPayload | None = None
    summary: str | None = None


KINDS = {"people": "person", "places": "place"}  # a vault folder, as the refusal names it


def opened_in(pack: Mapping[str, Any] | None) -> dict[str, str]:
    """The notes a recall opened, for whatever reason, each with its folder: {"jason": "people", "hansen": ""}."""
    out: dict[str, str] = {}
    for item in (pack or {}).get("items") or []:
        path = PurePosixPath(str(item.get("note") or ""))
        if path.stem:
            out[path.stem] = str(path.parent).strip(".")
    return out


def named_in(pack: Mapping[str, Any] | None) -> dict[str, str]:
    """The notes a recall found by name (its `used.names`), each with its folder: {"jason": "people"}. A note the
    pack opened for another reason (a date, a link, near in meaning) is not named."""
    names = set(((pack or {}).get("used") or {}).get("names") or [])
    return {n: f for n, f in opened_in(pack).items() if n in names}


async def _named_before(ctx: ToolContext) -> dict[str, str]:
    """What memory finds named in the last few messages, asked once a turn. A memory that does not answer names
    nothing, and the write goes on as it went before."""
    heard = ctx.heard
    if heard.named_before is None:
        pack = None
        if heard.before:
            try:
                payload = RecallPayload(query=heard.before, budget=ctx.recall_budget)
                pack = await ctx.bus.request("rpc.memory.recall", payload, timeout=5.0)
            except Exception:
                pack = None
        heard.named_before = named_in(pack if pack and pack.get("ok", True) else None)
    return heard.named_before


def _guess(note: str, folder: str, same: list[str], where: str) -> str:
    names = f"{', '.join(same[:-1])} and {same[-1]}"
    return (
        f"not saved: Hansen's message does not name the {KINDS.get(folder, 'note')} it is about, and {names} {where}, "
        f"so {note} is a guess. Call `ask` with them as the choices, and remember it once Hansen picks."
    )


async def unclear(note: str, ctx: ToolContext) -> str:
    """Why writing to `note` is a guess, or "". Hansen's message names no note of its kind, and the note is one of
    two or more of that kind named just before ("remember he got promoted", after lunch with Jason and Kevin), or,
    with none of them named before, one of two or more people or places memory opened for the message ("she got the
    job", with Mei and Lin in memory). The one note of its kind named just before is who a "he" means. Hansen's own
    note is never a guess, and memory is asked about the thread only for a note the message does not name."""
    heard = ctx.heard
    if note == ctx.source or note in heard.named:
        return ""
    spoken = set(heard.named.values())  # the message names one of that kind: the note is that one, or another
    before = await _named_before(ctx)
    if (folder := before.get(note)) is not None:
        same, where = [n for n, f in before.items() if f == folder], "were all named just before"
    elif (folder := heard.opened.get(note)) in KINDS:
        same, where = [n for n, f in heard.opened.items() if f == folder], "all came up in memory"
    else:
        return ""
    return _guess(note, folder, same, where) if len(same) > 1 and folder not in spoken else ""


async def remember(args: RememberArgs, ctx: ToolContext) -> dict[str, Any]:
    if why := await unclear(args.note, ctx):
        return {"ok": False, "error": why}
    payload = RememberPayload(
        note=args.note,
        source=ctx.source,
        type=args.type,
        aliases=args.aliases or None,
        fact=FactPayload(text=args.fact, day=args.day) if args.fact else None,
        summary=args.summary,
    )
    return await ctx.bus.request("rpc.memory.remember", payload.model_dump(mode="json", exclude_none=True), timeout=5.0)


REMEMBER = Tool(
    name="remember",
    description=(
        "Write to long-term memory. Use when Hansen states a durable fact about a person, place, project, "
        "routine, thing or himself, or asks you to remember something. The note is the entity "
        "(lowercase slug: mei, ramen-place-xinyi, hansen); the fact is one dated line about it. "
        "Put [[other-note]] around names of other notes. Only about the one Hansen's words name or can only mean: "
        "when a she, he or that place could be more than one, call `ask` first instead of picking one."
    ),
    args=RememberArgs,
    handler=remember,
)


# ---- recall ----------------------------------------------------------------------------------------


class RecallArgs(BaseModel):
    query: str = Field(min_length=1, description="a name, place, project or date to open")
    budget: int | None = Field(default=None, ge=1, le=20, description="max notes to open; default 8")


class RecallPayload(BaseModel):
    """The rpc.memory.recall request."""

    query: str
    budget: int = Field(ge=1)


async def recall(args: RecallArgs, ctx: ToolContext) -> dict[str, Any]:
    payload = RecallPayload(query=args.query, budget=args.budget or ctx.recall_budget)
    return await ctx.bus.request("rpc.memory.recall", payload, timeout=5.0)


RECALL = Tool(
    name="recall",
    description="Open more memory when the pack below is not enough: another name, place, project or date.",
    args=RecallArgs,
    handler=recall,
)
