"""`stay_quiet`: a check-in's way of saying nothing (services/main/service.py, `check_in`). Only check-ins have it: a
message from Hansen always gets an answer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .base import Tool, ToolContext


class StayQuietArgs(BaseModel):
    why: str = Field(min_length=1, max_length=300, description="in a line, why nothing is worth a message now")


async def stay_quiet(args: StayQuietArgs, ctx: ToolContext) -> dict[str, Any]:
    return {"ok": True}


STAY_QUIET = Tool(
    name="stay_quiet",
    description=(
        "Send Hansen nothing this time, and say why in a line. Call it, and write nothing, when no message is "
        "worth Hansen's attention now."
    ),
    args=StayQuietArgs,
    handler=stay_quiet,
)
