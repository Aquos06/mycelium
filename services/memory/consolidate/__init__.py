"""Nightly consolidation (MEMORY.md §3): one local day of events -> one model call -> the vault.

    the day's events ──► write_day (a forced tool call, validated as DayDigest) ──► summaries/YYYY/MM/DD.md
                                                                                ├► dated facts on the notes they belong to
                                                                                ├► new notes for new entities
                                                                                └► rewritten current states
    the week's days  ──► write_period (PeriodDigest) ──► summaries/YYYY/Wnn.md     when a Sunday is consolidated
    the month's days ──► write_period                ──► summaries/YYYY/MM.md      when its last day is

One object per concern:

    prompts.py       what the model reads: Prompt(system, user), day_prompt(), period_prompt(), the renderers
    tools.py         what the model answers through: StructuredTool, WRITE_DAY, WRITE_PERIOD
    model.py         ModelCaller: the forced tool call against the gateway, retried once with the field errors
    linking.py       autolink(), plain(), has_fact(): ordinary code around the model's text
    writer.py        DigestWriter: a DayDigest into the vault (notes, facts, summary), only what changed
    rollups.py       Rollups: a week or month from its day summaries, and which periods a day closes
    traces.py        trace.consolidate and trace.rollup
    consolidator.py  Consolidator: run(day) and rollup(period, key), the facade the service and schedule call

Runs for yesterday from the nightly schedule (schedule.py) and for any day on rpc.memory.consolidate
(`mctl consolidate 2026-10-14`); a week or month on rpc.memory.rollup (`mctl rollup 2026-W42`).
Idempotent per day: the summary is rewritten; a fact is skipped when the note already has the same line
that day, links or no links. Every run is traced, failed ones included. Shapes: schemas/consolidate.py.
"""

from .consolidator import Consolidator
from .errors import ConsolidationError
from .linking import autolink, has_fact, plain
from .model import ModelCaller
from .prompts import Prompt, day_prompt, describe, period_prompt, render_events, render_notes, render_recorded
from .rollups import Rollups
from .tools import WRITE_DAY, WRITE_PERIOD, StructuredTool
from .writer import DigestWriter

TOOL_NAME = WRITE_DAY.name
PERIOD_TOOL = WRITE_PERIOD.name

__all__ = [
    "Consolidator",
    "ConsolidationError",
    "DigestWriter",
    "ModelCaller",
    "PERIOD_TOOL",
    "Prompt",
    "Rollups",
    "StructuredTool",
    "TOOL_NAME",
    "WRITE_DAY",
    "WRITE_PERIOD",
    "autolink",
    "day_prompt",
    "describe",
    "has_fact",
    "period_prompt",
    "plain",
    "render_events",
    "render_notes",
    "render_recorded",
]
