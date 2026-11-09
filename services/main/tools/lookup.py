"""What the supervisor and the builder say of one module, for the tools that change or delete it.

Best effort: the builder checks again at the tap, so a supervisor or a builder that does not answer only means its
refusal would come then.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from mycelium_sdk import NoAnswer, Refused, ask

from .base import ToolContext

M = TypeVar("M", bound=BaseModel)

BUSY = ("queued", "building")  # a build of it that has not ended


class SysRow(BaseModel):
    name: str
    status: str = ""
    version: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)


class SysList(BaseModel):
    """rpc.sys.list, as much of it as Main reads: the registry's rows, every module folder on disk (`folders`) and
    the ones in GROWN_DIR (`grown`, the modules the builder grew; the rest of `folders` are hand-written)."""

    modules: list[SysRow] = Field(default_factory=list)
    folders: list[str] = Field(default_factory=list)
    grown: list[str] = Field(default_factory=list)

    def names(self) -> set[str]:
        """Every module the supervisor knows of: listed, or a folder on disk."""
        return {r.name for r in self.modules} | set(self.folders)


class BuildBrief(BaseModel):
    name: str
    status: str


class BuildListCall(BaseModel):
    limit: int = 50


class Builds(BaseModel):
    """rpc.build.list, as much of it as the tools read."""

    builds: list[BuildBrief] = Field(default_factory=list)


class Found(BaseModel):
    """One module, as the supervisor and the builder see it."""

    grown: list[str]  # every module the builder grew, to name them in a refusal
    is_grown: bool  # its folder is in GROWN_DIR
    listed: bool  # the registry has a row for it
    folder: bool  # a folder on disk; one not grown is hand-written
    building: bool  # a build of it, new or a change, has not ended
    version: str | None  # its registry row's


async def ask_quietly(ctx: ToolContext, subject: str, reply: type[M], payload: BaseModel | None = None) -> M | None:
    """The reply, or None when there was none or it said no: a check that cannot be made is left to the tap."""
    try:
        return await ask(ctx.bus, subject, payload, reply, timeout=2.0)
    except (NoAnswer, Refused):
        return None


async def look_up(ctx: ToolContext, module: str) -> Found | None:
    """None when the supervisor did not answer (then nothing is known of it)."""
    listed, builds = await asyncio.gather(
        ask_quietly(ctx, "rpc.sys.list", SysList), ask_quietly(ctx, "rpc.build.list", Builds, BuildListCall())
    )
    if listed is None:
        return None
    row = next((r for r in listed.modules if r.name == module), None)
    return Found(
        grown=sorted(listed.grown),
        is_grown=module in listed.grown,
        listed=row is not None,
        folder=module in listed.folders,
        building=any(b.name == module and b.status in BUSY for b in builds.builds) if builds else False,
        version=(row.version or row.manifest.get("version")) if row else None,
    )
