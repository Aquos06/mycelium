"""rpc.build.start and rpc.build.get, as the builder answers them and Main and mctl ask them.

    rpc.build.start   BuildRequest -> StartReply
    rpc.build.get     BuildRef     -> the build's record (services/builder/schemas/build.py)

One definition for both sides, like llm.py for rpc.llm.*: the builder validates what arrives with the same
model Main fills, so the contract cannot drift between them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .manifest import NAME_RE, RESERVED

SPEC_MAX = 20_000


class BuildRequest(BaseModel):
    """A module to grow from a spec Hansen approved."""

    name: str
    spec: str = Field(min_length=20, max_length=SPEC_MAX)  # SPEC.md: what Hansen approved
    coder: str | None = None  # None: the builder's default
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
