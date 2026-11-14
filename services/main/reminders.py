"""Reminders Hansen sets in chat: what to say, when, and in which thread.

    remind {text, at | in_minutes, repeat}   tools/remind.py: kept here, one KV key each (reminder/<id>)
    cancel_reminder {id}                     its key deleted
    Main's reminder loop (service.py)        sends each at its minute, in the thread it was set in

A reminder goes out at its time whatever the wake policy says (quiet hours, a chat in progress, the day's budget):
Hansen chose the time. One that came due while Main was down goes out once Main is back, saying when it was due; a
repeating one then moves to its next time after now, so the times missed meanwhile are not sent one by one.

Times repeat on the wall clock of Main's time zone: a daily 09:00 stays 09:00 across a summer-time change.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import secrets
from datetime import datetime, time, timedelta, tzinfo
from enum import StrEnum

from pydantic import BaseModel, ValidationError, field_validator

from mycelium_sdk import KV, kv_key

log = logging.getLogger("mycelium.main")

PREFIX = "reminder"
SHOWN = 20  # reminders the planner sees, the soonest first


class Repeat(StrEnum):
    NEVER = "never"
    DAILY = "daily"
    WEEKDAYS = "weekdays"  # Monday to Friday
    WEEKLY = "weekly"  # on the weekday it was first due
    MONTHLY = "monthly"  # on the day of the month it was first due, or the month's last day

    @property
    def words(self) -> str:
        return {
            Repeat.NEVER: "once",
            Repeat.DAILY: "every day",
            Repeat.WEEKDAYS: "every weekday",
            Repeat.WEEKLY: "every week",
            Repeat.MONTHLY: "every month",
        }[self]


class Reminder(BaseModel):
    id: str
    text: str  # what Main tells Hansen then, as Hansen will read it
    due: str  # the next time it goes out (ISO, with its offset)
    repeat: Repeat = Repeat.NEVER
    day: int | None = None  # a monthly one's day of the month: the 31st stays the 31st where a month has one
    wall: str | None = None  # a repeating one's time of day, HH:MM on Hansen's clock: each next time is built from it
    channel: str  # where it was set, and where it goes
    thread: str
    created: str
    cause: str | None = None  # the message that set it

    @field_validator("due")
    @classmethod
    def _aware(cls, v: str) -> str:
        if datetime.fromisoformat(v).tzinfo is None:
            raise ValueError("a reminder's time needs its offset")
        return v

    def due_at(self) -> datetime:
        return datetime.fromisoformat(self.due)

    def after(self, now: datetime, zone: tzinfo) -> datetime | None:
        """Its next time strictly after `now`; None when it does not repeat."""
        if self.repeat == Repeat.NEVER:
            return None
        at = time.fromisoformat(self.wall) if self.wall else None
        local = self.due_at().astimezone(zone)
        while local <= now:
            local = step(local, self.repeat, self.day, at)
        return local

    def line(self, zone: tzinfo) -> str:
        """How the planner sees it: `a1b2c3 Fri 2026-11-20 09:00, every week: Time to pay the rent.`"""
        how = "" if self.repeat == Repeat.NEVER else f", {self.repeat.words}"
        return f"{self.id} {when(self.due_at(), zone)}{how}: {self.text}"


def step(local: datetime, repeat: Repeat, day: int | None = None, at: time | None = None) -> datetime:
    """One repeat on from `local` (aware, in Hansen's ZoneInfo), at `at` on the wall clock (default: local's own time
    of day). Built from the date and the time of day each time, so a time that did not exist one day (02:30 when summer
    time starts) is 03:30 that day only."""
    d = local.date()
    match repeat:
        case Repeat.DAILY:
            d += timedelta(days=1)
        case Repeat.WEEKDAYS:
            d += timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
        case Repeat.WEEKLY:
            d += timedelta(days=7)
        case Repeat.MONTHLY:
            year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
            d = d.replace(year=year, month=month, day=min(day or d.day, calendar.monthrange(year, month)[1]))
        case _:
            raise ValueError(f"{repeat} does not repeat")
    return datetime.combine(d, at or local.timetz().replace(tzinfo=None), tzinfo=local.tzinfo)


def on_a_weekday(local: datetime) -> datetime:
    """A weekday reminder's first time: a Saturday or a Sunday moves to Monday, at the same time of day."""
    d = local.date()
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return datetime.combine(d, local.timetz().replace(tzinfo=None), tzinfo=local.tzinfo)


def when(t: datetime, zone: tzinfo) -> str:
    """Fri 2026-11-20 09:00, in Hansen's zone."""
    return f"{t.astimezone(zone):%a %Y-%m-%d %H:%M}"


class ReminderStore:
    """One key per reminder. Main is the only writer of these keys, so they are read from the bucket once and kept in
    memory: listing them (each turn, and the loop) never scans the bucket again. `lock` is held to send one and to
    cancel one, so a reminder cancelled while it goes out is never saved back with its next time. `changed` is set on
    each change, so Main's reminder loop looks again at once."""

    def __init__(self, kv: KV) -> None:
        self.kv = kv
        self.lock = asyncio.Lock()
        self.changed = asyncio.Event()
        self._kept: dict[str, Reminder] | None = None  # by id, once read

    async def _all(self) -> dict[str, Reminder]:
        """Read once; one that does not read is left out (and logged), never the rest."""
        if self._kept is None:
            kept: dict[str, Reminder] = {}
            for key in await self.kv.keys(f"{PREFIX}/"):
                if (raw := await self.kv.get(key)) is None:
                    continue
                try:
                    r = Reminder.model_validate(raw)
                except ValidationError as e:
                    log.warning("reminder %s does not read: %s", key, e)
                    continue
                kept[r.id] = r
            self._kept = kept
        return self._kept

    async def get(self, reminder_id: str) -> Reminder | None:
        return (await self._all()).get(reminder_id)

    async def save(self, reminder: Reminder) -> None:
        await self.kv.put(kv_key(PREFIX, reminder.id), reminder.model_dump(mode="json"))
        (await self._all())[reminder.id] = reminder
        self.changed.set()

    async def delete(self, reminder_id: str) -> None:
        await self.kv.delete(kv_key(PREFIX, reminder_id))
        (await self._all()).pop(reminder_id, None)
        self.changed.set()

    async def new_id(self) -> str:
        while await self.get(rid := secrets.token_hex(3)) is not None:
            continue
        return rid

    async def all(self) -> list[Reminder]:
        """Every reminder set, the soonest first."""
        return sorted((await self._all()).values(), key=lambda r: r.due_at())
