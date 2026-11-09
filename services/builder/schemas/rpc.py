"""rpc.build.* requests and replies: the contract Main and mctl code against.

    rpc.build.start   BuildRequest       -> StartReply
    rpc.build.get     BuildRef           -> BuildRecord (build.py)
    rpc.build.list    BuildListRequest   -> BuildList, newest first
    rpc.build.coders  {}                 -> CoderList
    rpc.build.default CoderChoice        -> CoderList (the web app's Settings → Builder, mctl coders --use)
    rpc.build.remove  RemoveRequest      -> Removed (a module deleted: Main's Delete it, the module page, mctl remove)

The handler adds ok=true; errors are {"ok": false, "error": "<field>: <message>"}. BuildRequest, StartReply,
BuildRef, RemoveRequest and Removed live in the SDK (mycelium_sdk.build), since Main fills them; they are re-exported
here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mycelium_sdk.build import SPEC_MAX, BuildRef, BuildRequest, BuildSummary, Removed, RemoveRequest, StartReply

__all__ = [
    "SPEC_MAX",
    "BuildList",
    "BuildListRequest",
    "BuildRef",
    "BuildRequest",
    "CoderChoice",
    "CoderInfo",
    "CoderList",
    "CoderSetting",
    "Removed",
    "RemoveRequest",
    "StartReply",
]


class BuildListRequest(BaseModel):
    limit: int = 20  # kept between 1 and 100


class BuildList(BaseModel):
    builds: list[BuildSummary] = Field(default_factory=list)


class CoderInfo(BaseModel):
    name: str
    description: str = ""  # what it is and what it runs on
    ready: bool
    reason: str | None = None  # why it cannot build now


class CoderList(BaseModel):
    default: str  # the one a request without `coder` gets: the last one chosen, else BUILDER_CODER
    seed: str  # BUILDER_CODER: the default until one is chosen
    coders: list[CoderInfo]


class CoderChoice(BaseModel):
    """rpc.build.default: which coder a build gets when it names none. Builds already waiting keep theirs."""

    coder: str = Field(min_length=1)


class CoderSetting(BaseModel):
    """The chosen default as the `builder` KV bucket keeps it, so a restart keeps the choice. When and by whom it
    changed is on the bus (build.coder), not here."""

    coder: str
