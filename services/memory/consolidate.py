"""Nightly consolidation (MEMORY.md §3): one local day of events -> one model call -> the vault.

    the day's events ──► write_day (a forced tool call, validated as DayDigest) ──► summaries/YYYY/MM/DD.md
                                                                                ├► dated facts on the notes they belong to
                                                                                ├► new notes for new entities
                                                                                └► rewritten current states

Runs for yesterday from the nightly schedule (schedule.py) and for any day on rpc.memory.consolidate
(`mctl consolidate 2026-10-14`). Idempotent per day: the summary is rewritten; a fact is skipped when
the note already has one from the same event, or the same text on that day. Every fact carries
`ev:<id>` when the model named the events it came from, `consolidation` when it was inferred. Every
run is traced on trace.consolidate with its cost. The shapes live in schemas/consolidate.py.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterable
from datetime import date
from typing import Any

from pydantic import ValidationError

from mycelium_sdk import Bus, input_schema, validation_message

from .events import EventSource
from .index import Index
from .indexer import index_file
from .schemas import (
    ConsolidateTrace,
    ConsolidationReport,
    DayDigest,
    Event,
    Fact,
    FactRecord,
    ModelRequest,
    Note,
    NoteType,
)
from .vault import LINK_RE, Vault, summary_path

log = logging.getLogger("mycelium.memory.consolidate")

TOOL_NAME = "write_day"
MAX_LINE = 200  # chars of one event in the prompt
MAX_NOTES = 300  # known notes listed in the prompt

SYSTEM = f"""You are the nightly consolidation of Hansen's memory (the project is called mycelium). You read one local day of raw events from his personal assistant and keep what matters, through the `{TOOL_NAME}` tool.

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

WRITE_DAY_TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": "Write the day: its summary, the facts worth keeping and the notes whose state changed.",
    "input_schema": input_schema(DayDigest),
}


class ConsolidationError(ValueError):
    """The model could not be reached or never produced a valid digest. Clean reply, no stack trace."""


# ---- the prompt ------------------------------------------------------------------------------------


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


def user_message(day: date, tz: str, notes: str, recorded: str, events: str, count: int) -> str:
    return (
        f"Day: {day:%A} {day.isoformat()} ({tz}).\n\nKnown notes:\n{notes}\n\n"
        f"Already recorded for this day (do not repeat):\n{recorded}\n\nEvents ({count}):\n{events}"
    )


# ---- the job ---------------------------------------------------------------------------------------


class Consolidator:
    def __init__(
        self,
        bus: Bus,
        vault: Vault,
        index: Index,
        events: EventSource,
        tz: str,
        slot: str = "consolidate",
        timeout: float = 180.0,
        max_tokens: int = 4096,
        max_event_chars: int = 24_000,
        max_rounds: int = 2,
    ) -> None:
        self.bus = bus
        self.vault = vault
        self.index = index
        self.events = events
        self.tz = tz
        self.slot = slot
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.max_event_chars = max_event_chars
        self.max_rounds = max_rounds

    async def run(self, day: date, cause: str | None = None) -> ConsolidationReport:
        t0 = time.monotonic()
        events = await self.events.for_day(day, self.tz)
        if not events:
            report = ConsolidationReport(day=day, skipped=True, reason="no events", latency_ms=_ms(t0))
            await self._trace(report, ok=True, cause=cause)
            return report
        try:
            digest, report = await self._digest(day, events, cause)
        except ConsolidationError as e:
            failed = ConsolidationReport(day=day, events=len(events), latency_ms=_ms(t0))
            await self._trace(failed, ok=False, cause=cause, error=str(e))
            raise
        await self._apply(day, digest, events, report)
        report.latency_ms = _ms(t0)
        await self._trace(report, ok=True, cause=cause)
        return report

    # ---- model -----------------------------------------------------------------------------

    async def _digest(self, day: date, events: list[Event], cause: str | None) -> tuple[DayDigest, ConsolidationReport]:
        report = ConsolidationReport(day=day, events=len(events))
        prompt = user_message(
            day,
            self.tz,
            render_notes(self.vault.notes()),
            render_recorded(await self.index.facts(day=day)),
            render_events(events, self.max_event_chars),
            len(events),
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        error = ""
        for _round in range(self.max_rounds):
            request = ModelRequest(
                slot=self.slot,
                system=SYSTEM,
                messages=messages,
                tools=[WRITE_DAY_TOOL],
                tool_choice=TOOL_NAME,
                max_tokens=self.max_tokens,
                cause=cause,
                timeout=self.timeout,
            )
            try:
                reply = await self.bus.request("rpc.llm.complete", request, timeout=self.timeout + 5)
            except Exception as e:
                raise ConsolidationError(f"gateway unreachable: {type(e).__name__}: {e}") from e
            if not reply.get("ok"):
                raise ConsolidationError(str(reply.get("error") or "gateway error"))
            report.rounds += 1
            report.model = reply.get("model")
            report.cost_usd = round(report.cost_usd + float(reply.get("cost_usd") or 0), 6)
            calls = [c for c in reply.get("tool_calls") or [] if c.get("name") == TOOL_NAME]
            if not calls:
                raise ConsolidationError(f"model did not call {TOOL_NAME}")
            call = calls[0]
            try:
                return DayDigest.model_validate(call.get("input") or {}), report
            except ValidationError as e:
                error = validation_message(e, "digest")
                log.warning("digest for %s rejected (round %d): %s", day, report.rounds, error)
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "id": call["id"], "name": TOOL_NAME, "input": call.get("input") or {}}
                        ],
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": call["id"],
                                "content": json.dumps({"ok": False, "error": error}, ensure_ascii=False),
                            }
                        ],
                    }
                )
        raise ConsolidationError(f"no valid digest after {self.max_rounds} rounds: {error}")

    # ---- vault -----------------------------------------------------------------------------

    async def _apply(self, day: date, digest: DayDigest, events: list[Event], report: ConsolidationReport) -> None:
        known_ids = {e.id for e in events}
        vocabulary = await self.index.vocabulary()
        touched: dict[str, Note] = {}
        created: set[str] = set()

        async def note_for(slug: str, type: NoteType | None, aliases: list[str]) -> Note:
            if slug in touched:
                note = touched[slug]
            elif record := await self.index.get(slug):
                note = self.vault.read(record.path)
            else:
                note_type = type or "thing"
                note = Note(name=slug, path=self.vault.path_for(slug, note_type), type=note_type)
                created.add(slug)
            for alias in aliases:
                if alias not in note.aliases and alias != note.name:
                    note.aliases.append(alias)
            touched[slug] = note
            return note

        for f in digest.facts:
            note = await note_for(f.note, f.type, f.aliases)
            ids = [i for i in f.events if i in known_ids]  # the model may misremember an id
            source = f"ev:{ids[0]}" if ids else "consolidation"
            if _has_fact(note, day, f.text, source):
                report.facts_skipped += 1
                continue
            note.facts.insert(0, Fact(day=day, text=autolink(f.text, vocabulary), source=source))
            report.facts_added += 1

        for u in digest.updates:
            if u.note not in touched and await self.index.get(u.note) is None:
                log.info("update for unknown note %r ignored", u.note)
                continue
            note = await note_for(u.note, None, [])
            note.summary = u.summary

        for note in touched.values():
            self.vault.write(note)
            await index_file(self.vault, self.index, note.path)
        report.notes_created = sorted(created)
        report.notes_updated = sorted(set(touched) - created)

        path = summary_path(day)
        self.vault.write_text(path, autolink(digest.summary, vocabulary))
        await index_file(self.vault, self.index, path)
        report.summary_path = path

    async def _trace(
        self, report: ConsolidationReport, *, ok: bool, cause: str | None, error: str | None = None
    ) -> None:
        trace = ConsolidateTrace(cause=cause, hops=1 if cause else 0, ok=ok, report=report, error=error)
        await self.bus.publish("trace.consolidate", trace)


CJK_RE = re.compile(r"[぀-ヿ一-鿿]")


def autolink(text: str, vocabulary: list[tuple[str, str]]) -> str:
    """Wrap known names and aliases the model left bare in [[slug|term]], once per note, outside existing links.

    Ordinary code, not model compliance: the summary links like the rest of the vault, so recall can hop.
    """
    spans = [m.span() for m in LINK_RE.finditer(text)]
    linked = {m.group(1).strip().lower() for m in LINK_RE.finditer(text)}
    for term, name in sorted(vocabulary, key=lambda t: -len(t[0])):
        if name in linked or len(term) < 2:
            continue
        pattern = re.escape(term) if CJK_RE.search(term) else r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        for m in re.finditer(pattern, text, re.IGNORECASE):
            if any(s <= m.start() < e for s, e in spans):
                continue
            shown = m.group(0)
            link = f"[[{name}]]" if shown.lower() == name else f"[[{name}|{shown}]]"
            text = text[: m.start()] + link + text[m.end() :]
            spans = [m2.span() for m2 in LINK_RE.finditer(text)]
            linked.add(name)
            break
    return text


def _has_fact(note: Note, day: date, text: str, source: str) -> bool:
    """Idempotency: the same event already produced a fact that day, or the same line is already there."""
    wanted = " ".join(text.split()).lower()
    for f in note.facts:
        if f.day != day:
            continue
        if source.startswith("ev:") and f.source == source:
            return True
        if " ".join(f.text.split()).lower() == wanted:
            return True
    return False


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)
