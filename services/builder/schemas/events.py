"""The build.* events: build.started, build.progress (one per round), build.done, build.failed."""

from __future__ import annotations

from mycelium_sdk import Envelope

from .build import BuildMode, FeedbackStage, Stage


class BuildEvent(Envelope):
    build_id: str
    name: str
    coder: str
    mode: BuildMode = BuildMode.NEW  # a change keeps the module running as it was until its new version deploys


class BuildStarted(BuildEvent):
    pass


class BuildProgress(BuildEvent):
    round: int
    stage: FeedbackStage
    passed: bool


class BuildDone(BuildEvent):
    version: str
    commit: str | None = None
    image: str | None = None
    rounds: int
    seconds: float
    cost_usd: float = 0.0
    channel: str | None = None
    thread: str | None = None


class BuildFailed(BuildEvent):
    stage: Stage
    error: str
    output: str = ""
    rounds: int
    seconds: float
    cost_usd: float = 0.0
    channel: str | None = None
    thread: str | None = None
