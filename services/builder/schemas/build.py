"""One build: its record in the `builder` KV bucket, its rounds, and where it is or where it stopped."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from mycelium_sdk import Envelope, new_id, now_iso


class BuildStatus(StrEnum):
    QUEUED = "queued"
    BUILDING = "building"
    DONE = "done"
    FAILED = "failed"


class Stage(StrEnum):
    """Where a build is, or where it stopped."""

    CODER = "coder"  # the coder writing
    CHECKS = "checks"  # the static checks
    VERIFY = "verify"  # the supervisor's verify: its image build, then the tests
    BUILD = "build"
    TESTS = "tests"
    PROMOTE = "promote"  # promote + commit
    DEPLOY = "deploy"
    RESTART = "restart"  # the builder restarted while it ran


# the stages a round can end in, and so what the next round fixes from
FeedbackStage = Literal[Stage.CODER, Stage.CHECKS, Stage.BUILD, Stage.TESTS]


class Round(BaseModel):
    """One pass of coder -> checks -> verify, and where it stopped."""

    n: int = Field(ge=1)
    stage: FeedbackStage  # how far it got: "tests" with passed=True is a module that works
    passed: bool = False
    output: str = ""  # the problems, or the tail of the build log or of pytest's output
    note: str = ""  # the coder's own line about what it did
    log: str = ""  # the tail of what an agent printed while it worked
    calls: int = 0  # model calls this round
    cost_usd: float = 0.0
    seconds: float = 0.0


class BuildSummary(BaseModel):
    """A record without the spec and the round output: what rpc.build.list holds."""

    id: str
    name: str
    coder: str
    status: BuildStatus
    created: str
    started: str | None = None
    finished: str | None = None
    stage: Stage | None = None  # where a failed build stopped
    error: str | None = None
    rounds: int = 0
    version: str | None = None
    commit: str | None = None
    cost_usd: float = 0.0


class BuildRecord(BaseModel):
    """One build, from queued to done or failed; rpc.build.get answers it."""

    id: str = Field(default_factory=new_id)
    name: str
    spec: str
    coder: str
    status: BuildStatus = BuildStatus.QUEUED
    created: str = Field(default_factory=now_iso)
    started: str | None = None
    finished: str | None = None
    cause: str | None = None
    hops: int = 0
    channel: str | None = None
    thread: str | None = None
    rounds: list[Round] = Field(default_factory=list)
    stage: Stage | None = None
    error: str | None = None
    output: str = ""  # the last failure's output, for whoever reads a failed build
    version: str | None = None
    commit: str | None = None  # the commit in GROWN_DIR: the rollback point
    image: str | None = None
    model: str | None = None  # the model the coder used, when it says
    cost_usd: float = 0.0

    def summary(self) -> BuildSummary:
        return BuildSummary.model_validate(
            {**self.model_dump(exclude={"rounds", "spec", "output"}), "rounds": len(self.rounds)}
        )

    def envelope(self) -> Envelope:
        """build.* events are caused by the message that asked for the build, one hop further."""
        return Envelope(source="builder", cause=self.cause, hops=self.hops + 1)
