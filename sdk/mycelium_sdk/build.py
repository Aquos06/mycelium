"""The builder's contract, as the builder speaks it and Main, mctl and the web app read it.

    rpc.build.start   BuildRequest -> StartReply: a new module from a spec, or a change to one the builder grew
    rpc.build.get     BuildRef     -> BuildRecord
    build.started / build.stage / build.progress / build.done / build.failed: the BuildEvent kinds below
    build.coder       CoderChosen: the default coder changed (not about one build)

One definition for both sides, like llm.py for rpc.llm.*: the builder validates what arrives with the same model
Main fills, and builds each event with the model Main reads it back with, so the contract cannot drift between them.

Each event carries the thread that asked for the build (channel, thread: none for `mctl`), so whoever told it there
can tell it how it goes. build.stage, build.done and build.failed carry the whole picture so far, every finished
round in a line (`history`), so a reader that comes in late (the app opened mid-build, Main restarted) needs only
the last one; `seq` orders them, as a reader may get two close together in either order.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from .envelope import Envelope, new_id, now_iso
from .manifest import NAME_RE, RESERVED

SPEC_MAX = 20_000
CHANGE_MAX = 4_000
TEXT_MIN = 20


# ---- rpc.build.start / get ---------------------------------------------------------------------------


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


# ---- one build -------------------------------------------------------------------------------------------


class BuildMode(StrEnum):
    NEW = "new"  # a module from a spec
    CHANGE = "change"  # a module the builder grew, edited as it is; its data is kept


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
    SNAPSHOT = "snapshot"  # a change: the module's data copied before the new version touches it
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
    summary: str = ""  # one line on how it ended: "the tests pass (6 passed)", "tests failed: 1 failed, 5 passed; …"
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
    mode: BuildMode = BuildMode.NEW
    base_version: str | None = None  # a change: the version it started from
    created: str
    started: str | None = None
    finished: str | None = None
    stage: Stage | None = None  # where a building build is, or where a failed one stopped
    since: str | None = None  # while it builds: when it entered that stage
    error: str | None = None
    rounds: int = 0
    version: str | None = None
    commit: str | None = None
    cost_usd: float = 0.0


class BuildRecord(BaseModel):
    """One build, from queued to done or failed; rpc.build.get answers it."""

    id: str = Field(default_factory=new_id)
    name: str
    spec: str  # SPEC.md as the coder reads it; a change build's ends with the change
    coder: str
    mode: BuildMode = BuildMode.NEW
    change: str = ""  # a change build: what Hansen approved, also the last section of `spec`
    base_version: str | None = None  # a change build: the version it starts from
    base_commit: str | None = None  # and its commit in GROWN_DIR: where to go back to
    snapshot: str | None = None  # a change build: the copy of the module's data taken before it deployed
    status: BuildStatus = BuildStatus.QUEUED
    created: str = Field(default_factory=now_iso)
    started: str | None = None
    finished: str | None = None
    cause: str | None = None
    hops: int = 0
    channel: str | None = None
    thread: str | None = None
    rounds: list[Round] = Field(default_factory=list)
    stage: Stage | None = None  # where it is; once it ended, where a failed one stopped
    since: str | None = None  # while it builds: when it entered `stage`
    seq: int = 0  # build.stage / done / failed events so far: each carries the next, so a reader keeps the newest
    error: str | None = None
    output: str = ""  # the last failure's output, for whoever reads a failed build
    version: str | None = None
    commit: str | None = None  # the commit in GROWN_DIR: the rollback point
    image: str | None = None
    model: str | None = None  # the model the coder used, when it says
    cost_usd: float = 0.0

    def summary(self) -> BuildSummary:
        return BuildSummary.model_validate(
            {**self.model_dump(exclude={"rounds", "spec", "change", "output", "seq"}), "rounds": len(self.rounds)}
        )

    def seconds(self) -> float:
        """How long it ran, from its start to its end (0 until both are known)."""
        try:
            return round(
                (
                    datetime.fromisoformat(self.finished or "") - datetime.fromisoformat(self.started or "")
                ).total_seconds(),
                1,
            )
        except ValueError:
            return 0.0

    def ended(self) -> BuildDone | BuildFailed | None:
        """How it ended, as its build.done or build.failed said it; None while it is queued or building. For a
        reader that missed the event (Main, after a restart)."""
        if self.status == BuildStatus.DONE:
            return BuildDone.of(self, self.seconds())
        if self.status == BuildStatus.FAILED:
            return BuildFailed.of(self, self.seconds())
        return None


# ---- the build.* events ----------------------------------------------------------------------------------


class RoundLine(BaseModel):
    """One finished round, in a line: how far it got, whether it passed, and why it stopped."""

    n: int
    stage: FeedbackStage
    passed: bool
    summary: str = ""
    seconds: float = 0.0

    @classmethod
    def of(cls, rnd: Round) -> RoundLine:
        return cls(n=rnd.n, stage=rnd.stage, passed=rnd.passed, summary=rnd.summary, seconds=rnd.seconds)

    @classmethod
    def every(cls, record: BuildRecord) -> list[RoundLine]:
        return [cls.of(r) for r in record.rounds]


class BuildEvent(Envelope):
    source: str = "builder"
    build_id: str
    name: str
    coder: str
    mode: BuildMode = BuildMode.NEW  # a change keeps the module running as it was until its new version deploys
    channel: str | None = None  # where it was asked for
    thread: str | None = None

    @classmethod
    def about(cls, record: BuildRecord, **fields: Any) -> Self:
        """This event about `record`: caused by the message that asked for the build, one hop further, and
        addressed to the thread that asked. `fields` are the event's own."""
        return cls(
            cause=record.cause,
            hops=record.hops + 1,
            build_id=record.id,
            name=record.name,
            coder=record.coder,
            mode=record.mode,
            channel=record.channel,
            thread=record.thread,
            **fields,
        )


class BuildStarted(BuildEvent):
    max_rounds: int = 0
    base_version: str | None = None

    @classmethod
    def of(cls, record: BuildRecord, max_rounds: int) -> BuildStarted:
        return cls.about(record, max_rounds=max_rounds, base_version=record.base_version)


class BuildStage(BuildEvent):
    """Where the build is now: a round's coder, checks or verify, then snapshot, promote, deploy."""

    stage: Stage
    round: int  # the round it is in; after the rounds, how many it took
    max_rounds: int
    since: str  # when it entered this stage
    seq: int
    base_version: str | None = None
    history: list[RoundLine] = Field(default_factory=list)

    @classmethod
    def of(cls, record: BuildRecord, n: int, max_rounds: int) -> BuildStage:
        """The record as it enters `record.stage`, in round `n`."""
        return cls.about(
            record,
            stage=record.stage,
            round=n,
            max_rounds=max_rounds,
            since=record.since or now_iso(),
            seq=record.seq,
            base_version=record.base_version,
            history=RoundLine.every(record),
        )


class BuildProgress(BuildEvent):
    """A round ended."""

    round: int
    max_rounds: int = 0
    stage: FeedbackStage
    passed: bool
    summary: str = ""
    seconds: float = 0.0

    @classmethod
    def of(cls, record: BuildRecord, rnd: Round, max_rounds: int) -> BuildProgress:
        return cls.about(
            record,
            round=rnd.n,
            max_rounds=max_rounds,
            stage=rnd.stage,
            passed=rnd.passed,
            summary=rnd.summary,
            seconds=rnd.seconds,
        )


class BuildEnded(BuildEvent):
    """What build.done and build.failed both say: the rounds it took, how long, what it cost, each round in a line."""

    rounds: int
    seconds: float
    cost_usd: float = 0.0
    seq: int = 0
    base_version: str | None = None
    history: list[RoundLine] = Field(default_factory=list)

    @classmethod
    def ended(cls, record: BuildRecord, seconds: float, **fields: Any) -> Self:
        return cls.about(
            record,
            rounds=len(record.rounds),
            seconds=seconds,
            cost_usd=record.cost_usd,
            seq=record.seq,
            base_version=record.base_version,
            history=RoundLine.every(record),
            **fields,
        )


class BuildDone(BuildEnded):
    version: str
    commit: str | None = None
    image: str | None = None

    @classmethod
    def of(cls, record: BuildRecord, seconds: float) -> BuildDone:
        return cls.ended(record, seconds, version=record.version, commit=record.commit, image=record.image)


class BuildFailed(BuildEnded):
    stage: Stage
    error: str
    output: str = ""

    @classmethod
    def of(cls, record: BuildRecord, seconds: float) -> BuildFailed:
        return cls.ended(record, seconds, stage=record.stage, error=record.error, output=record.output)


class CoderChosen(Envelope):
    """build.coder: the coder a build gets when it names none changed (the web app's Settings → Builder, mctl
    coders --use). Not about one build, so not a BuildEvent: it is the record of who switched it, and when."""

    source: str = "builder"
    coder: str
    previous: str
    seed: str  # BUILDER_CODER: choosing it again clears the choice
