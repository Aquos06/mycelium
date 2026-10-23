"""What the planner sees: the system prompt. The tools it may call live in `tools/`.

Planner context = policy + state snapshot + recall pack + the last N turns (docs/MEMORY.md §5).
v0 has no snapshot and a fixed policy; both are plain text here until Main owns a database.
"""

from __future__ import annotations

from datetime import date
from typing import Any

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
        lines.append(f"- {m.name}: {m.purpose.strip()} Requests: {reqs}")
    return "\n".join(lines)


def system_prompt(
    today: date,
    tz: str,
    channel: str,
    pack: dict[str, Any] | None,
    modules: list[ModuleInfo],
    recall_error: str | None = None,
) -> str:
    return f"""You are Main, Hansen's personal assistant (the project is called mycelium). You are talking with Hansen over {channel}.
Today is {today.strftime("%A")} {today.isoformat()} ({tz}).

How you work:
- Be brief and concrete. Hansen writes short messages; answer in the same register and in the language he used.
- The memory below was opened for this message, and each line says why. Use it. If it has nothing relevant, say so instead of guessing.
- Use `remember` when Hansen states a durable fact or asks you to remember something. One call per entity.
- Use `recall` when you need memory the pack does not have (another person, place, project or date).
- Modules hold exact data. Use `ask_module` instead of estimating numbers, lists or history.
- Use `ask` when a decision is Hansen's. Never claim to have done something you did not do.
- Never invent memories, events or people.

Memory for this message:
{render_pack(pack, recall_error)}

Modules:
{render_modules(modules)}"""
