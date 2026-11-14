"""What a coder is given and gives back, and what our coder's forced tools take.

Feedback        what the next round fixes from: the stage that failed and its output
CoderContext    one round for one coder: the build, its folder, the feedback, the brief
CoderResult     what a coder says it did
ManifestDraft   write_manifest's arguments: what the module listens to, emits and answers
WriteFiles      write_files's arguments: whole files (FileArg) and a note
Spend           a build's model calls and cost so far, against CODER_MAX_CALLS and CODER_MAX_USD
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from mycelium_sdk.build import FeedbackStage

from ..prompts.brief import Brief


class Feedback(BaseModel):
    stage: FeedbackStage
    output: str


class CoderContext(BaseModel):
    build_id: str
    name: str
    spec: str
    dir: Path  # GROWN_DIR/.staging/<name>: the only place a coder writes
    round: int
    fresh: bool  # no round has delivered files yet: write the module from the start
    change: str = ""  # a change build: what to change in the module that is there (fresh is then never true)
    feedback: Feedback | None = None  # what failed last round, and its output
    brief: Brief


class CoderResult(BaseModel):
    note: str = ""  # one line: what it did
    log: str = ""  # the tail of what an agent printed while it worked
    calls: int = 0  # model calls
    cost_usd: float = 0.0
    model: str | None = None


class RequestDraft(BaseModel):
    """One request the module answers, described: Main reads this to call it."""

    name: str = Field(description="relative action, e.g. add or summary (answered on rpc.mod.<name>.<action>)")
    description: str = Field(min_length=8, description="what it does, one sentence")
    params: dict[str, str] = Field(
        default_factory=dict,
        description='what it takes, name -> type: {"amount": "number", "day": "optional date"}',
    )
    returns: dict[str, str] = Field(default_factory=dict, description='what it gives back: {"total": "number"}')


class ManifestDraft(BaseModel):
    purpose: str = Field(min_length=10, description="one sentence: what the module does for Hansen")
    need: str = Field(default="", description="the need from the spec, in one sentence")
    subscribes: list[str] = Field(default_factory=list, description="full subjects it listens to, e.g. sense.chat")
    emits: list[str] = Field(
        default_factory=list, description="relative event names, e.g. expense.logged (sent as mod.<name>.<event>)"
    )
    requests: list[RequestDraft] = Field(
        default_factory=list, description="every request it answers, each described: Main reads these to call it"
    )
    interval_seconds: list[int] = Field(default_factory=list, description="periodic hooks, each at least 10")
    daily: list[str] = Field(
        default_factory=list, description='times in the user\'s day as "HH:MM", e.g. ["21:00"]: run by @mod.at("21:00")'
    )


class FileArg(BaseModel):
    path: str = Field(description="relative path, e.g. app/main.py or tests/test_expenses.py")
    content: str = Field(description="the whole file")


class WriteFiles(BaseModel):
    files: list[FileArg] = Field(min_length=1, max_length=8)
    note: str = Field(default="", description="one line: what you wrote or changed, and why")


class Spend(BaseModel):
    build_id: str
    calls: int = 0
    cost_usd: float = 0.0
    model: str | None = None
