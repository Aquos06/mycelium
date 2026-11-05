"""rpc.build.start and rpc.build.get, as the builder answers them and Main and mctl ask them.

    rpc.build.start   BuildRequest -> StartReply: a new module from a spec, or a change to one the builder grew
    rpc.build.get     BuildRef     -> the build's record (services/builder/schemas/build.py)

One definition for both sides, like llm.py for rpc.llm.*: the builder validates what arrives with the same
model Main fills, so the contract cannot drift between them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from .manifest import NAME_RE, RESERVED

SPEC_MAX = 20_000
CHANGE_MAX = 4_000
TEXT_MIN = 20


class BuildRequest(BaseModel):
    """A module to grow from a spec Hansen approved (`spec`), or a change he approved to one the builder grew
    (`change`): one of the two. A change build edits the module as it is and keeps its data."""

    name: str
    spec: str = Field(default="", max_length=SPEC_MAX)  # SPEC.md: what Hansen approved
    change: str = Field(default="", max_length=CHANGE_MAX)  # what to change in the module, as Hansen approved it
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

    @field_validator("spec", "change")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _spec_or_change(self) -> BuildRequest:
        if self.spec and self.change:
            raise ValueError("a build takes a spec (a new module) or a change (to one the builder grew), not both")
        if len(self.spec or self.change) < TEXT_MIN:
            what = "a change says what the module should do now" if self.change else "a spec says what the module does"
            raise ValueError(f"{what}: at least {TEXT_MIN} characters")
        if self.spec:
            self.spec += "\n"
        return self

    @property
    def is_change(self) -> bool:
        return bool(self.change)


class StartReply(BaseModel):
    build_id: str
    position: int  # builds ahead of this one: 0 starts now


class BuildRef(BaseModel):
    build_id: str = Field(min_length=1)
