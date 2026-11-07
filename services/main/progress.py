"""A build Main started, as one message that changes in place (out.progress, schemas.Progress).

The builder says where a build is (build.stage) and how it ended (build.done / build.failed), each with every
finished round in a line; this turns that into the steps Hansen reads in the thread that asked:

    Building expenses
    ❌ Round 1: tests failed: 1 failed, 5 passed; test_add_keeps_the_day: KeyError: 'day' · 3 min
    ⏳ Round 2 of 6: fixing what failed (since 14:05)
    ▫️ Save it
    ▫️ Start it

A change has one more step before Save: its data is copied first. Rendered from the event alone, so Main keeps no
state for it and a restart loses nothing: the next event has the whole picture again.
"""

from __future__ import annotations

import math
from datetime import datetime, tzinfo

from mycelium_sdk.build import BuildDone, BuildFailed, BuildMode, BuildStage, RoundLine, Stage
from mycelium_sdk.text import one_line

from .schemas import ProgressStep, StepState

ROUND_STAGES = {Stage.CODER, Stage.CHECKS, Stage.VERIFY, Stage.BUILD, Stage.TESTS}
MARK = {StepState.DONE: "✅", StepState.FAILED: "❌", StepState.ACTIVE: "⏳", StepState.PENDING: "▫️"}
ERROR_SHOWN = 160  # of a failure's error, on its step; the say after it has more

Card = tuple[str, list[ProgressStep]]  # the title, and the steps under it


def _after(change: bool) -> list[tuple[Stage, str]]:
    """The steps after the rounds: the stage that does each, and how it reads."""
    if change:
        return [
            (Stage.SNAPSHOT, "Copy its data"),
            (Stage.PROMOTE, "Save the new version"),
            (Stage.DEPLOY, "Start the new version"),
        ]
    return [(Stage.PROMOTE, "Save it"), (Stage.DEPLOY, "Start it")]


def duration(seconds: float) -> str:
    """ "42 s", "3 min", "1 h 5 min". Rounded half up, as the web app's took() rounds, so the two say the same."""
    s = max(0, math.floor(seconds + 0.5))
    if s < 60:
        return f"{s} s"
    m = math.floor(s / 60 + 0.5)
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60} min" if m % 60 else f"{m // 60} h"


def _doing(stage: Stage, n: int, change: bool) -> str:
    if stage == Stage.CODER:
        return "fixing what failed" if n > 1 else ("writing the change" if change else "writing the module")
    if stage == Stage.CHECKS:
        return "checking the files"
    return "building it and running its tests"


def _rounds(history: list[RoundLine]) -> list[ProgressStep]:
    steps = []
    for r in history:
        what = r.summary or ("the tests pass" if r.passed else f"stopped at {r.stage}")
        took = f" · {duration(r.seconds)}" if r.seconds else ""
        steps.append(
            ProgressStep(text=f"Round {r.n}: {what}{took}", state=StepState.DONE if r.passed else StepState.FAILED)
        )
    return steps


def running(ev: BuildStage) -> Card:
    """Where a build is: its rounds so far, the step it is on, and the steps still to come."""
    change = ev.mode == BuildMode.CHANGE
    steps = _rounds(ev.history)
    if ev.stage in ROUND_STAGES and ev.round > len(ev.history):
        of = f" of {ev.max_rounds}" if ev.max_rounds else ""
        steps.append(
            ProgressStep(
                text=f"Round {ev.round}{of}: {_doing(ev.stage, ev.round, change)}",
                state=StepState.ACTIVE,
                since=ev.since,
            )
        )
    keys = [k for k, _ in _after(change)]
    at = keys.index(ev.stage) if ev.stage in keys else -1
    steps += [
        ProgressStep(
            text=text,
            state=StepState.DONE if i < at else StepState.ACTIVE if i == at else StepState.PENDING,
            since=ev.since if i == at else None,
        )
        for i, (_, text) in enumerate(_after(change))
    ]
    if change:
        return f"Changing {ev.name}" + (f" (now v{ev.base_version})" if ev.base_version else ""), steps
    return f"Building {ev.name}", steps


def ended(ev: BuildDone | BuildFailed) -> Card:
    """How a build ended: every step ticked, or where it stopped and why."""
    change = ev.mode == BuildMode.CHANGE
    after = _after(change)
    steps = _rounds(ev.history)

    if isinstance(ev, BuildDone):
        steps += [ProgressStep(text=text, state=StepState.DONE) for _, text in after]
        if change:
            base = f": v{ev.base_version} → v{ev.version}" if ev.base_version else ""
            return f"Changed {ev.name}{base}", steps
        return f"Built {ev.name} v{ev.version}", steps

    error = one_line(ev.error or "no reason given", ERROR_SHOWN)
    keys = [k for k, _ in after]
    if ev.stage in keys:
        at = keys.index(ev.stage)
        steps += [
            ProgressStep(
                text=f"{text}: {error}" if i == at else text,
                state=StepState.DONE if i < at else StepState.FAILED if i == at else StepState.PENDING,
            )
            for i, (_, text) in enumerate(after)
        ]
    else:
        last = ev.history[-1].summary if ev.history else ""
        if not error.startswith("no working module") and error[:40] not in last:  # the last round said it already
            steps.append(ProgressStep(text=f"Stopped: {error}", state=StepState.FAILED))
        steps += [ProgressStep(text=text, state=StepState.PENDING) for _, text in after]
    return f"{'Changing' if change else 'Building'} {ev.name} failed", steps


def as_text(title: str, steps: list[ProgressStep], zone: tzinfo) -> str:
    """The card in plain lines, for a channel that shows only text (Telegram)."""
    lines = [title]
    for s in steps:
        when = ""
        if s.state == StepState.ACTIVE and s.since:
            try:
                when = f" (since {datetime.fromisoformat(s.since).astimezone(zone):%H:%M})"
            except ValueError:
                pass
        lines.append(f"{MARK[s.state]} {s.text}{when}")
    return "\n".join(lines)
