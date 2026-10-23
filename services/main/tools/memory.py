"""The memory tools: `remember` writes to the vault, `recall` opens more of it (rpc.memory.*)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .base import Tool, ToolContext

NoteType = Literal["self", "person", "place", "project", "thing", "routine", "module"]


# ---- remember --------------------------------------------------------------------------------------


class RememberArgs(BaseModel):
    note: str = Field(min_length=1, description="entity slug, lowercase, e.g. mei or ramen-place-xinyi")
    type: NoteType | None = Field(default=None, description="only used when the note is new")
    aliases: list[str] = Field(default_factory=list, description="other names, e.g. 小美")
    fact: str | None = Field(default=None, description="one line, past tense, e.g. 'is moving to Tainan in December'")
    day: date | None = Field(default=None, description="YYYY-MM-DD the fact is about; default today")
    summary: str | None = Field(default=None, description="replace the note's current-state paragraph")

    @model_validator(mode="after")
    def _day_needs_a_fact(self) -> RememberArgs:
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


async def remember(args: RememberArgs, ctx: ToolContext) -> dict[str, Any]:
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
        "Put [[other-note]] around names of other notes."
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
