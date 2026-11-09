"""`delete_module`: ask Hansen to delete a whole module the builder grew, when he says he wants it gone.

Like `change_module`: the planner names the module; code checks that it is one the builder grew (or one still listed
whose folder is gone already) and is not being built now. A valid call ends the turn, Main stores it as a proposal
(proposals.py, kind `delete`) and sends a card with Delete it / Keep it. Only a tap deletes it (rpc.build.remove), in
code. Its data is copied aside first and its code stays in GROWN_DIR's history, so it can come back.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .base import Tool, ToolContext
from .lookup import look_up


class DeleteArgs(BaseModel):
    module: str = Field(description="the module to delete, as listed under Modules: one marked grown")

    @field_validator("module", mode="before")
    @classmethod
    def _slug(cls, v: Any) -> Any:
        return re.sub(r"[\s_]+", "-", v.strip().lower()) if isinstance(v, str) else v

    @property
    def name(self) -> str:
        """The module, under the name a proposal goes by."""
        return self.module

    def card(self, version: str | None = None) -> str:
        """What Hansen reads before he chooses."""
        now = f" (v{version})" if version else ""
        return "\n".join(
            [
                f"Delete {self.module}{now}?",
                "It stops for good and leaves your modules. Its data is copied aside first and its code stays in "
                "git, so it can come back. Nothing is deleted until you choose.",
            ]
        )


async def delete(args: DeleteArgs, ctx: ToolContext) -> dict[str, Any]:
    """Refused when the module is hand-written, not there, or being built now; best effort (lookup.py)."""
    found = await look_up(ctx, args.module)
    if found is None:
        return {"ok": True, "delete": args.module}
    if not found.is_grown and found.folder:
        error = f"{args.module} is hand-written, not grown: only modules marked grown can be deleted. Tell Hansen."
        return {"ok": False, "error": error}
    if not found.is_grown and not found.listed:
        names = ", ".join(found.grown) or "none"
        return {"ok": False, "error": f"there is no module {args.module!r} to delete (grown: {names})."}
    if found.building:
        return {
            "ok": False,
            "error": f"{args.module} is being built or changed right now: tell Hansen to ask again once it is done.",
        }
    return {"ok": True, "delete": args.module, "version": found.version}


DELETE_MODULE = Tool(
    name="delete_module",
    description=(
        "Ask Hansen to delete a whole module marked grown, when he says he wants it gone: one he no longer uses, a "
        "duplicate, one that should not exist. Never for an entry inside a module (that is `change_module`), and "
        "never on your own idea. Ends your turn with a card (Delete it / Keep it); nothing is deleted until he "
        "chooses, and its data is copied aside first."
    ),
    args=DeleteArgs,
    handler=delete,
)
