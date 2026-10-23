"""`ask`: hand the decision to Hansen.

The handler does nothing on the bus. Main's loop sees validated AskArgs in the outcome, ends the
turn and publishes out.ask; the answer comes back as the next message of the thread.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .base import Tool, ToolContext


class AskArgs(BaseModel):
    text: str = Field(min_length=1, description="the question")
    choices: list[str] = Field(min_length=2, max_length=6, description="2 to 6 short options")


async def ask(_args: AskArgs, _ctx: ToolContext) -> dict[str, Any]:
    return {"ok": True, "asked": True}


ASK = Tool(
    name="ask",
    description=(
        "Ask Hansen to choose before you act, when the decision is his. Ends your turn; his answer arrives "
        "as the next message. Never pretend to have acted."
    ),
    args=AskArgs,
    handler=ask,
)
