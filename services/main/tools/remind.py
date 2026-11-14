"""The reminder tools: `remind` sets one, `cancel_reminder` takes one away (../reminders.py keeps them, Main's
reminder loop sends them)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from ..reminders import Reminder, Repeat, on_a_weekday, when
from .base import Tool, ToolContext

FURTHEST = timedelta(days=366)
WITH_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}")  # a date alone would be midnight

# ---- remind ----------------------------------------------------------------------------------------


class RemindArgs(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=500,
        description="what you will tell Hansen when it is time, in the language Hansen writes in: 'Time to pay the rent.'",
    )
    at: str | None = Field(default=None, description="when, on Hansen's clock: YYYY-MM-DD HH:MM")
    in_minutes: int | None = Field(
        default=None, ge=1, le=366 * 24 * 60, description="instead of `at`, for 'in 20 minutes' or 'in 2 hours' (120)"
    )
    repeat: Repeat = Field(
        default=Repeat.NEVER,
        description="never; daily; weekdays (Monday to Friday); weekly (on the weekday of `at`); monthly (on its day)",
    )

    @field_validator("at")
    @classmethod
    def _readable(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("write `at` as YYYY-MM-DD HH:MM") from None
        if not WITH_TIME.match(v):
            raise ValueError("`at` needs a time of day, YYYY-MM-DD HH:MM: if Hansen gave none, ask when") from None
        return v

    @model_validator(mode="after")
    def _one_time(self) -> RemindArgs:
        if (self.at is None) == (self.in_minutes is None):
            raise ValueError("give exactly one of `at` or `in_minutes`")
        return self

    def due(self, now: datetime, zone: ZoneInfo) -> datetime:
        """`at` is on Hansen's wall clock (an offset written with it is honoured); `in_minutes` counts from now."""
        if self.in_minutes is not None:
            return (now + timedelta(minutes=self.in_minutes)).astimezone(zone).replace(second=0, microsecond=0)
        t = datetime.fromisoformat(self.at or "")
        return t.replace(tzinfo=zone) if t.tzinfo is None else t.astimezone(zone)


async def remind(args: RemindArgs, ctx: ToolContext) -> dict[str, Any]:
    if ctx.reminders is None or not ctx.channel:
        return {"ok": False, "error": "reminders are not kept here"}
    zone = ZoneInfo(ctx.tz)
    now = ctx.now or datetime.now(UTC)
    due = args.due(now, zone)
    if args.repeat == Repeat.WEEKDAYS:
        due = on_a_weekday(due)  # "every weekday at 9:30", said on a Saturday: Monday first
    if due <= now:
        return {"ok": False, "error": f"{when(due, zone)} has passed: it is {when(now, zone)} now"}
    if due - now > FURTHEST:
        return {"ok": False, "error": f"{when(due, zone)} is more than a year away"}
    text = args.text.strip()
    for r in await ctx.reminders.all():  # asked twice, called twice or set in two chats: one reminder
        if (r.text, r.due_at(), r.repeat) == (text, due, args.repeat):
            return {"ok": True, "id": r.id, "when": when(due, zone), "repeat": args.repeat.words, "already_set": True}
    reminder = Reminder(
        id=await ctx.reminders.new_id(),
        text=text,
        due=due.isoformat(),
        repeat=args.repeat,
        day=due.day if args.repeat == Repeat.MONTHLY else None,
        wall=None if args.repeat == Repeat.NEVER else f"{due:%H:%M}",
        channel=ctx.channel,
        thread=ctx.thread,
        created=now.isoformat(),
        cause=ctx.cause,
    )
    await ctx.reminders.save(reminder)
    return {"ok": True, "id": reminder.id, "when": when(due, zone), "repeat": args.repeat.words}


REMIND = Tool(
    name="remind",
    description=(
        "Set a reminder: at that time you tell Hansen `text` on your own, in this chat. Only when Hansen asks for one "
        "in this message ('remind me Friday at 9 to pay rent', 'ping me in 20 minutes', 'every Monday at 8 tell me "
        "to...'), one call per reminder. Never on your own: an appointment or plan Hansen mentions is `remember`ed, and "
        "you may ask in your reply whether Hansen wants a reminder."
    ),
    args=RemindArgs,
    handler=remind,
)


# ---- cancel_reminder -------------------------------------------------------------------------------


class CancelReminderArgs(BaseModel):
    id: str = Field(min_length=1, description="the reminder's id, as listed under Reminders")


async def cancel_reminder(args: CancelReminderArgs, ctx: ToolContext) -> dict[str, Any]:
    if ctx.reminders is None:
        return {"ok": False, "error": "reminders are not kept here"}
    async with ctx.reminders.lock:  # not while it goes out: it would be saved back with its next time
        reminder = await ctx.reminders.get(args.id.strip())
        if reminder is not None:
            await ctx.reminders.delete(reminder.id)
    if reminder is None:
        ids = [r.id for r in await ctx.reminders.all()]
        return {"ok": False, "error": f"no reminder {args.id!r}; the ones set: {ids or 'none'}"}
    return {"ok": True, "cancelled": reminder.text, "was_due": when(reminder.due_at(), ZoneInfo(ctx.tz))}


CANCEL_REMINDER = Tool(
    name="cancel_reminder",
    description=(
        "Take a reminder away, by its id under Reminders, when Hansen no longer wants it. To move one to another "
        "time, cancel it and `remind` again."
    ),
    args=CancelReminderArgs,
    handler=cancel_reminder,
)
