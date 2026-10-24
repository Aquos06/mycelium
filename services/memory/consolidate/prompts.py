"""What the model reads. A Prompt is the system text and the user message; the builders render the
day's material (known notes, what is already recorded, the events) or a period's day summaries into it.

Everything here is deterministic text. Change the wording here, never inside the job.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date

from pydantic import BaseModel, ConfigDict

from ..schemas import Event, FactRecord, Note, SummaryRecord

MAX_LINE = 200  # chars of one event in the prompt
MAX_NOTES = 300  # known notes listed in the prompt

DAY_SYSTEM = """You are the nightly consolidation of Hansen's memory (the project is called mycelium). You read one local day of raw events from his personal assistant and keep what matters, through the `write_day` tool.

How to write:
- summary: the day in three to six sentences, past tense, concrete (who, where, how much). Put [[slug]] around every note you mention, existing or new.
- facts: one line each about one entity, past tense, with the ids of the events it comes from. Keep what will matter later: people, places, plans, decisions, changes of state. Skip routine noise (single expenses, lights, presence) unless it says something new.
- Use the known notes by their slug. Create a note only for an entity that will come up again, with a type and its other names. Slugs are lowercase: mei, ramen-place-xinyi.
- Exact data lives in modules (expenses, ...): mention totals in the summary, do not copy line items into notes.
- updates: rewrite a note's current state only when the day made it wrong or stale.
- Facts listed under "already recorded" are in memory: do not repeat them or rephrase them; add only what is new.
- sense.chat lines are what Hansen said; out.say / out.notify lines are the assistant's own replies and sys.* lines are the system talking to itself. Facts come from what Hansen said and what modules observed, never from the assistant's replies ("the memory was updated" is not a fact about anyone).
- Put event ids only in `events`, never in the summary or in a fact's text.
- Never invent. If nothing is worth keeping, write a short summary and no facts.
- Write in the language of Hansen's own messages that day (his chat lines), not the language of the names in them; names stay in their own script."""

PERIOD_SYSTEM = """You write the {period} summary of Hansen's memory from its day summaries, through the `write_period` tool.

How to write:
- Four to eight sentences, past tense, concrete: what happened, what changed, what was decided, what repeated. Give totals over the period where the days give numbers.
- Keep the [[slug]] links of the notes that matter for the period; drop one-off noise (routine checks, single expenses, test messages).
- No event ids and no dates inside sentences unless the day itself matters; the period is already known.
- Never invent. Write in the language the day summaries use."""


class Prompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    system: str
    user: str


# ---- renderers --------------------------------------------------------------------------------------


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def describe(event: Event) -> str:
    """One line for one event: what was said or summarised, else the compact payload."""
    for key in ("text", "summary"):
        v = event.payload.get(key)
        if isinstance(v, str) and v.strip():
            return _clip(v, MAX_LINE)
    return _clip(json.dumps(event.payload, ensure_ascii=False, default=str), MAX_LINE)


def render_events(events: Iterable[Event], max_chars: int) -> str:
    lines = [f"#{e.id} {e.ts:%H:%M} {e.subject} ({e.source}): {describe(e)}" for e in events]
    out: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        if used + len(line) + 1 > max_chars:
            out.append(f"... {len(lines) - i} more events omitted (prompt budget)")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def render_notes(notes: Iterable[Note], limit: int = MAX_NOTES) -> str:
    rows = []
    for n in sorted(notes, key=lambda n: n.name)[:limit]:
        aliases = f"; aliases: {', '.join(n.aliases)}" if n.aliases else ""
        rows.append(f"- {n.name} ({n.type}{aliases}): {_clip(n.summary, 120)}".rstrip(": "))
    return "\n".join(rows) or "(none yet)"


def render_recorded(facts: Iterable[FactRecord]) -> str:
    rows = [f"- {f.note}: {f.text} ({f.source or 'unknown'})" for f in facts]
    return "\n".join(rows) or "(nothing yet)"


# ---- builders ---------------------------------------------------------------------------------------


def day_prompt(
    day: date, tz: str, notes: Iterable[Note], recorded: Iterable[FactRecord], events: list[Event], max_chars: int
) -> Prompt:
    user = (
        f"Day: {day:%A} {day.isoformat()} ({tz}).\n\nKnown notes:\n{render_notes(notes)}\n\n"
        f"Already recorded for this day (do not repeat):\n{render_recorded(recorded)}\n\n"
        f"Events ({len(events)}):\n{render_events(events, max_chars)}"
    )
    return Prompt(system=DAY_SYSTEM, user=user)


def period_prompt(period: str, key: str, days: list[date], summaries: list[SummaryRecord]) -> Prompt:
    lines = [f"- {s.key} ({date.fromisoformat(s.key):%A}): {' '.join(s.text.split())}" for s in summaries]
    user = f"Period: {period} {key} ({days[0].isoformat()} to {days[-1].isoformat()}).\n\nDay summaries:\n" + "\n".join(
        lines
    )
    return Prompt(system=PERIOD_SYSTEM.format(period=period), user=user)
