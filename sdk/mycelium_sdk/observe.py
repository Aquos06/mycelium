"""brain.observe: what a module tells Main, and how loud. A module sends it with
`mod.observe(type, summary, data, severity)`; Main reads it with this model.

    info    for the record. Main never wakes for it.
    notice  worth telling Hansen at the next good moment: Main wakes within minutes, and quiet hours, a chat in
            progress and the day's budget of messages hold it.
    alert   worth interrupting Hansen now: Main wakes at once, even in quiet hours. A module gets one an hour; more
            are told as notices.

The summary is what Hansen reads, as the module wrote it after the module's name ("expenses: Nothing logged
today."), so it is one short sentence addressed to Hansen. The same summary twice in a day is told once; the SDK's
own reports of a handler or a hook that failed (ERRORS) are told once a day per module, whatever they say.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from .envelope import Envelope

ERRORS = ("handler.error", "hook.error")  # observed by the SDK when a module's code raised


class Severity(StrEnum):
    INFO = "info"
    NOTICE = "notice"
    ALERT = "alert"


class Observation(Envelope):
    source: str  # the module
    type: str = ""  # what kind of thing happened: "nothing_logged", "big_expense"
    summary: str = ""  # one sentence for Hansen; without one, there is nothing to tell
    severity_hint: Severity = Severity.INFO
    data: dict[str, Any] = Field(default_factory=dict)
