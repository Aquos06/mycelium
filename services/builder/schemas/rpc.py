"""rpc.build.* requests and replies: the contract Main and mctl code against.

    rpc.build.start   BuildRequest       -> StartReply
    rpc.build.get     BuildRef           -> BuildRecord (build.py)
    rpc.build.list    BuildListRequest   -> BuildList, newest first
    rpc.build.coders  {}                 -> CoderList
    rpc.build.default CoderChoice        -> CoderList (the web app's Settings → Builder, mctl coders --use)

The handler adds ok=true; errors are {"ok": false, "error": "<field>: <message>"}.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from mycelium_sdk import now_iso
from mycelium_sdk.manifest import NAME_RE, RESERVED

from .build import BuildSummary

SPEC_MAX = 20_000


class BuildRequest(BaseModel):
    """A module to grow from a spec Hansen approved."""

    name: str
    spec: str = Field(min_length=20, max_length=SPEC_MAX)  # SPEC.md: what Hansen approved
    coder: str | None = None  # None: BUILDER_CODER
    cause: str | None = None  # the message that asked (an approval tap): build.* events point back at it
    hops: int = Field(default=0, ge=0)
    channel: str | None = None  # where the result goes back to (Main reads these)
    thread: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError("must be a lowercase slug, 2-31 chars, starting with a letter")
        if v in RESERVED:
            raise ValueError(f"{v!r} is reserved")
        return v

    @field_validator("spec")
    @classmethod
    def _spec(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 20:
            raise ValueError("a spec says what the module does: at least 20 characters")
        return v + "\n"


class StartReply(BaseModel):
    build_id: str
    position: int  # builds ahead of this one: 0 starts now


class BuildRef(BaseModel):
    build_id: str = Field(min_length=1)


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
    """The chosen default as the `builder` KV bucket keeps it, so a restart keeps the choice."""

    coder: str
    chosen: str = Field(default_factory=now_iso)
