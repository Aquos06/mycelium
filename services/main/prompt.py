"""What the planner reads: a Prompt (the SDK's), the system part and Hansen's message. The tools it may call
live in `tools/`. Changing the policy below is what scripts/bench_tools.py is for: run it before and after.

Planner context = policy + state snapshot + recall pack + the last N turns (docs/MEMORY.md §5).
v0 has no snapshot and a fixed policy; both are plain text here until Main owns a database.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mycelium_sdk import Prompt

from .proposals import Proposal, ProposalStatus
from .reminders import SHOWN, Reminder
from .schemas import ModuleInfo


def render_pack(pack: dict[str, Any] | None, error: str | None = None) -> str:
    if error:
        return f"(memory unavailable: {error})"
    items = (pack or {}).get("items") or []
    if not items:
        return "(nothing matched: no known name or date in the message)"
    return "\n".join(f"- {it['note']} ({it['why']}): {it.get('excerpt', '')}".rstrip(": ") for it in items)


def render_modules(modules: list[ModuleInfo]) -> str:
    """The running modules with their requests, then the ones that are not running: a thread may still say one
    runs ("expenses is built and running"), and the model believes the thread unless told here."""
    running = [m for m in modules if m.status == "running"]
    gone = [m for m in modules if m.status != "running"]
    lines = [] if running else ["(none running)"]
    for m in running:
        listens = f" Listens to: {', '.join(m.listens)}." if m.listens else ""
        head = f"- {m.name}{_grown(m)}: {m.purpose.strip()}{listens}"
        if not m.specs:  # a module whose requests are only named
            lines.append(f"{head} Requests: {', '.join(m.requests) or 'no requests'}")
            continue
        lines.append(f"{head} Requests (send the fields shown in `args`):")
        for r in m.requests:
            spec = m.specs.get(r)
            if spec is None:
                lines.append(f"  - {r}: not described")
                continue
            returns = f" Returns {{{', '.join(f'{k}: {t}' for k, t in spec.returns.items())}}}." if spec.returns else ""
            lines.append(f"  - {r} {spec.signature()}: {spec.description.strip()}{returns}")
        if m.views:
            views = ", ".join(f"{m.name}.{vid} ({v.title or vid}, {v.kind})" for vid, v in m.views.items())
            lines.append(f"  Views (`show` one by name): {views}")
    if gone:
        names = ", ".join(f"{m.name} ({m.status})" for m in gone)
        lines.append(f"Not running now (an earlier message may say otherwise; do not call them): {names}")
    return "\n".join(lines)


def _grown(m: ModuleInfo) -> str:
    """A module the builder grew can be changed (`change_module`); a hand-written one cannot."""
    if not m.grown:
        return ""
    return f" (grown, v{m.version})" if m.version else " (grown)"


def render_proposals(
    proposals: list[Proposal], running: set[str] | None = None, here: tuple[str, str] | None = None
) -> str:
    """Modules already offered and not running, and changes and deletions asked for and not made: so the planner does
    not offer one again, or offers it knowingly. A card is "there" only in the chat it went to; a module built and since
    retired (or deleted) can be offered again."""
    lines = []
    for p in proposals:
        since = (p.decided or p.created)[:10]
        if p.is_delete:
            if state := _delete_state(p, since, here):
                lines.append(f"- deleting {p.name} ({state})")
            continue
        if p.is_change:
            if state := _change_state(p, since, here):
                lines.append(f"- a change to {p.name}: {p.purpose.strip()} ({state})")
            continue
        match p.status:
            case ProposalStatus.DONE if running is None or p.name in running:
                continue  # under Modules
            case ProposalStatus.DONE:
                state = f"built on {since} but not running now: if he wants it, call `propose_module` for it again"
            case ProposalStatus.PROPOSED if here is not None and (p.channel, p.thread) != here:
                state = (
                    f"offered {p.created[:10]} in another chat, still waiting there: if he asks here, call "
                    "`propose_module` here"
                )
            case ProposalStatus.PROPOSED:
                state = f"offered {p.created[:10]}, waiting for his Build it: do not offer it again, the card is there"
            case ProposalStatus.DECLINED:
                state = f"he chose Not now on {since}: do not offer it again unless he asks for it"
            case ProposalStatus.BUILDING:
                state = f"being built since {since}: do not offer it again"
            case _:
                state = f"its build failed on {since}: call `propose_module` again only if he asks for it"
        lines.append(f"- {p.name}: {p.purpose.strip()} ({state})")
    return "\n".join(lines) or "(none)"


def _change_state(p: Proposal, since: str, here: tuple[str, str] | None) -> str:
    """A change's line, or "" once it is made (the module under Modules has it)."""
    match p.status:
        case ProposalStatus.DONE:
            return ""
        case ProposalStatus.PROPOSED if here is not None and (p.channel, p.thread) != here:
            return f"offered {p.created[:10]} in another chat: if he asks here, call `change_module` here"
        case ProposalStatus.PROPOSED:
            return f"offered {p.created[:10]}, waiting for his Change it: do not offer it again, the card is there"
        case ProposalStatus.DECLINED:
            return f"he chose Not now on {since}: do not offer it again unless he asks for it"
        case ProposalStatus.BUILDING:
            return f"being made since {since}; {p.name} runs as it was until then"
        case _:
            return f"it failed on {since} and {p.name} runs as it was: call `change_module` again only if he asks"


def _delete_state(p: Proposal, since: str, here: tuple[str, str] | None) -> str:
    """A deletion's line, or "" once it is done (the module is gone from Modules, and so is what was offered of it)."""
    match p.status:
        case ProposalStatus.DONE:
            return ""
        case ProposalStatus.PROPOSED if here is not None and (p.channel, p.thread) != here:
            return f"asked {p.created[:10]} in another chat: if he asks here, call `delete_module` here"
        case ProposalStatus.PROPOSED:
            return f"asked {p.created[:10]}, waiting for his Delete it: do not ask again, the card is there"
        case ProposalStatus.DECLINED:
            return f"he chose Keep it on {since}: do not ask again unless he asks for it"
        case _:
            return f"it did not go through on {since} ({p.short_note()}): call `delete_module` again only if he asks"


def render_reminders(reminders: list[Reminder], tz: str) -> str:
    """The reminders set and not sent yet, the soonest first, with the id `cancel_reminder` takes."""
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    lines = [f"- {r.line(zone)}" for r in reminders[:SHOWN]]
    if len(reminders) > SHOWN:
        lines.append(f"(and {len(reminders) - SHOWN} more, later)")
    return "\n".join(lines) or "(none)"


def planner_prompt(
    today: date,
    tz: str,
    channel: str,
    text: str,
    pack: dict[str, Any] | None,
    modules: list[ModuleInfo],
    recall_error: str | None = None,
    proposals: list[Proposal] | None = None,
    thread: str | None = None,
    now: time | None = None,
    reminders: list[Reminder] | None = None,
) -> Prompt:
    """One turn: the policy, today and the time, the memory opened for this message, the modules, the ones offered
    and the reminders set; then the message."""
    here = (channel, thread) if thread is not None else None
    system = _system(today, tz, channel, pack, modules, recall_error, proposals or [], here, now, reminders or [])
    return Prompt(system=system, user=text)


def _system(
    today: date,
    tz: str,
    channel: str,
    pack: dict[str, Any] | None,
    modules: list[ModuleInfo],
    recall_error: str | None,
    proposals: list[Proposal],
    here: tuple[str, str] | None = None,
    now: time | None = None,
    reminders: list[Reminder] | None = None,
) -> str:
    clock = f"\n\nIt is {now:%H:%M} now." if now is not None else ""  # last: what comes before changes once a day
    return f"""You are Main, Hansen's personal assistant (the project is called mycelium). You are talking with Hansen over {channel}.
Today is {today.strftime("%A")} {today.isoformat()} ({tz}).

How you work:
- Be brief and concrete. Hansen writes short messages; answer in the same register and in the language he used.
- Earlier messages in this conversation start with their date: a "today" or "yesterday" in them is relative to that date, not to today.
- The memory below was opened for this message, and each line says why. Use it. If it has nothing relevant, say so instead of guessing.
- Use `remember` when Hansen states a durable fact, logs something no module below takes (money spent, a reading, a plan) or asks you to remember something. One call per entity.
- Use `recall` when you need memory the pack does not have (another person, place, project or date). What Hansen did, said or planned on a day, in a week or with someone is memory: recall it; a module only has its own numbers.
- Only the modules listed under Modules are running now; an earlier message about another module may be out of date.
- Modules hold exact data. Use `ask_module` instead of estimating numbers, lists or history. Send a request the fields its line shows, in `args`; for "how much" or "what did I" with no dates, ask for all of it, not only today.
- When Hansen logs something a module takes through a request like `add` (money spent, for expenses), send it there with `ask_module`, one call per entry, with the day it happened: that is where it belongs, not in memory.
- When a module's answer is something Hansen should see rather than read (a list of entries, totals by category or by day, a few figures, one record, a number against a goal), call `show`: a table, a chart, stats, details or a meter goes under your reply, made from the module's own data. A view listed under a module is the easy way (`show` with `view`: Main gets its data); otherwise call `ask_module` first and point `show` at its reply. Then say in a line or two what it means, and do not write out again what it shows.
- A module that listens to sense.chat hears Hansen's messages itself: when he logs something it tracks (dinner 350 for expenses), acknowledge it without logging it again.
- Use `change_module` when a module marked grown does something wrong, should work differently, or cannot do what Hansen asks of it (take an entry out, keep one more field, a total it does not give): say what it should do after the change. Saying it cannot is not enough: send the card that makes it able to. It keeps its data, and nothing changes until he chooses Change it. Offer a change only by calling `change_module`, never in words: its card is the only way he can make it. Do not `propose_module` a second module for what a running one should do; a module not marked grown cannot be changed, so say so.
- Use `delete_module` when Hansen wants a whole module marked grown gone (delete it, remove it, get rid of the duplicate, he no longer uses it): only on his word, never because you think one is unused. Its card (Delete it / Keep it) is the only way to delete one, so never say it is deleted, or will be, in words. Taking an entry out of a module is `change_module`, not this; a module not marked grown cannot be deleted, so say so.
- Use `propose_module` when Hansen wants something ongoing that no module above does: tracking or logging things over time, counts, totals, history. Draft it from his words; nothing is built until he chooses Build it. Offer a module only by calling `propose_module`: its card is the only way he can build it, so never offer to build or rebuild one in words.
- When he logs money spent, a count or a reading that no module above tracks, `remember` it first, then `propose_module` to track it from now on (`propose_module` ends your turn, so what is not remembered by then is lost). If a module under "Offered" below covers it, only `remember` it and do what its line says.
- Use `remind` when Hansen asks to be reminded, pinged or told something at a time (remind me, don't let me forget, at 9 tell me): `at` on Hansen's clock, worked out from today and the time at the end ("Friday" is the coming Friday, "tonight" is today), or `in_minutes` for "in 20 minutes"; `repeat` for every day, every weekday, every Monday or the same day each month. Write `text` as what you will say to Hansen then. With no time given, ask when in a line instead of guessing one. Set one only when Hansen asks for it: a plan with a date (a dentist appointment on Friday at 9) is `remember`, and you may offer a reminder for it in words.
- The reminders set and not sent yet are under Reminders below: answer from there when Hansen asks what is set. To take one away, `cancel_reminder` it by its id; to change its time or words, cancel it and `remind` again.
- Use `ask` when a decision is Hansen's.
- Only say you saved, logged, noted, remembered or set a reminder when a tool call did it in this turn. Never claim to have done something you did not do.
- Never invent memories, events or people.

Memory for this message:
{render_pack(pack, recall_error)}

Modules:
{render_modules(modules)}

Offered (modules and changes proposed to Hansen, not made yet):
{render_proposals(proposals, {m.name for m in modules if m.status == "running"}, here)}

Reminders (set, not sent yet; the id first):
{render_reminders(reminders or [], tz)}{clock}"""
