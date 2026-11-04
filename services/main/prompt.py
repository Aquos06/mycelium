"""What the planner reads: a Prompt (the SDK's), the system part and Hansen's message. The tools it may call
live in `tools/`. Changing the policy below is what scripts/bench_tools.py is for: run it before and after.

Planner context = policy + state snapshot + recall pack + the last N turns (docs/MEMORY.md §5).
v0 has no snapshot and a fixed policy; both are plain text here until Main owns a database.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mycelium_sdk import Prompt

from .proposals import Proposal, ProposalStatus
from .schemas import ModuleInfo


def render_pack(pack: dict[str, Any] | None, error: str | None = None) -> str:
    if error:
        return f"(memory unavailable: {error})"
    items = (pack or {}).get("items") or []
    if not items:
        return "(nothing matched: no known name or date in the message)"
    return "\n".join(f"- {it['note']} ({it['why']}): {it.get('excerpt', '')}".rstrip(": ") for it in items)


def render_modules(modules: list[ModuleInfo]) -> str:
    if not modules:
        return "(none deployed)"
    lines = []
    for m in modules:
        reqs = ", ".join(m.requests) or "no requests"
        listens = f" Listens to: {', '.join(m.listens)}." if m.listens else ""
        lines.append(f"- {m.name}: {m.purpose.strip()}{listens} Requests: {reqs}")
    return "\n".join(lines)


def render_proposals(proposals: list[Proposal]) -> str:
    """Modules already offered and not running: so the planner does not offer one again, or offers it knowingly."""
    if not proposals:
        return "(none)"
    lines = []
    for p in proposals:
        since = (p.decided or p.created)[:10]
        match p.status:
            case ProposalStatus.PROPOSED:
                state = f"offered {p.created[:10]}, waiting for his Build it: do not offer it again, the card is there"
            case ProposalStatus.DECLINED:
                state = f"he chose Not now on {since}: do not offer it again unless he asks for it"
            case ProposalStatus.BUILDING:
                state = f"being built since {since}: do not offer it again"
            case _:
                state = f"its build failed on {since}: offer it again only if he asks for it"
        lines.append(f"- {p.name}: {p.purpose.strip()} ({state})")
    return "\n".join(lines)


def planner_prompt(
    today: date,
    tz: str,
    channel: str,
    text: str,
    pack: dict[str, Any] | None,
    modules: list[ModuleInfo],
    recall_error: str | None = None,
    proposals: list[Proposal] | None = None,
) -> Prompt:
    """One turn: the policy, today, the memory opened for this message, the modules and the ones offered; then the
    message."""
    return Prompt(system=_system(today, tz, channel, pack, modules, recall_error, proposals or []), user=text)


def _system(
    today: date,
    tz: str,
    channel: str,
    pack: dict[str, Any] | None,
    modules: list[ModuleInfo],
    recall_error: str | None,
    proposals: list[Proposal],
) -> str:
    return f"""You are Main, Hansen's personal assistant (the project is called mycelium). You are talking with Hansen over {channel}.
Today is {today.strftime("%A")} {today.isoformat()} ({tz}).

How you work:
- Be brief and concrete. Hansen writes short messages; answer in the same register and in the language he used.
- Earlier messages in this conversation start with their date: a "today" or "yesterday" in them is relative to that date, not to today.
- The memory below was opened for this message, and each line says why. Use it. If it has nothing relevant, say so instead of guessing.
- Use `remember` when Hansen states a durable fact, logs something (money spent, a reading, a plan) or asks you to remember something. One call per entity.
- Use `recall` when you need memory the pack does not have (another person, place, project or date). What Hansen did, said or planned on a day, in a week or with someone is memory: recall it; a module only has its own numbers.
- Modules hold exact data. Use `ask_module` instead of estimating numbers, lists or history.
- A module that listens to sense.chat hears Hansen's messages itself: when he logs something it tracks (dinner 350 for expenses), acknowledge it without logging it again.
- Use `propose_module` when Hansen wants something ongoing that no module above does: tracking or logging things over time, counts, totals, history. Draft it from his words; nothing is built until he chooses Build it.
- When he logs money spent, a count or a reading that no module above tracks, `remember` it first, then `propose_module` to track it from now on (`propose_module` ends your turn, so what is not remembered by then is lost). If a module under "Offered" below covers it, only `remember` it and do what its line says.
- Use `ask` when a decision is Hansen's.
- Only say you saved, logged, noted or remembered something when a tool call did it in this turn. Never claim to have done something you did not do.
- Never invent memories, events or people.

Memory for this message:
{render_pack(pack, recall_error)}

Modules:
{render_modules(modules)}

Offered (modules proposed to Hansen, not running):
{render_proposals(proposals)}"""
