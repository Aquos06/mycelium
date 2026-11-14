"""Main's own looks at how things are, and what it may say without being asked.

What wakes Main:
    the timer (MAIN_WAKE_EVERY)   modules that stopped running, cards left waiting, anything held
    a module's notice             within a couple of minutes: notices that come together are one wake
    a module's alert              at once
An `info` observation never wakes it (mycelium_sdk.observe).

Each wake gathers what it could say (an Item) and the policy decides each one in code, in this order:
    muted     two of its module's messages got 👎 this week: dropped (one 👎: its alerts are told as notices)
    expired   a notice held longer than 10 hours: dropped, it was about a moment that has passed
    sent      an alert, at most one per module an hour: told even in quiet hours, mid-conversation or over the budget
    repeat    the same thing was told already: the same summary from the same module that day (any error the SDK
              reported for a module counts as one a day, since an exception's text changes each time): dropped
    held      quiet hours, a chat in progress in that thread, or the day's budget (MAIN_WAKE_BUDGET) spent: tried
              again at the next wake
    sent      none of the above
A held observation is kept short (its summary, not its data), five a module and twenty in all, so one noisy module
never pushes out another's and the state stays a small KV value.

Nothing here calls the model. A module's notice is told as the module wrote it, in the thread Hansen last wrote in
(on a channel of MAIN_WAKE_CHANNELS), or as an unaddressed out.notify before Hansen has written anywhere; a card is
shown again in its own thread. Each wake that told, dropped or newly held something publishes one trace.wake.

Keys in Main's bucket:
    wake/state    WakeState: today's count, what is held, what was told, modules seen down, 👎 per module
    wake/home     Home: the thread Hansen last wrote in
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, time, tzinfo
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from mycelium_sdk import KV, Envelope, Observation, Severity, cut, kv_key, one_line
from mycelium_sdk.observe import ERRORS

STATE_KEY = kv_key("wake", "state")
HOME_KEY = kv_key("wake", "home")
MAIN = "main"  # the source of what Main itself noticed (a module down, a card waiting): never muted
HELD_MAX = 20  # observations kept waiting; the oldest go first
HELD_PER_SOURCE = 5  # of them from one module: its own oldest go first
REPLIES_KEPT = 50  # messages remembered for the 👎 on them
SUMMARY_SHOWN = 300


class Verdict(StrEnum):
    SENT = "sent"
    QUIET = "held: quiet hours"
    BUSY = "held: a chat in progress"
    BUDGET = "held: today's budget is spent"
    REPEAT = "dropped: told already"
    EXPIRED = "dropped: held too long"
    MUTED = "dropped: its module was voted down"

    @property
    def held(self) -> bool:
        return self in (Verdict.QUIET, Verdict.BUSY, Verdict.BUDGET)


class ItemKind(StrEnum):
    OBSERVE = "observe"  # a module's notice or alert
    DOWN = "down"  # a module that should run and has not, at two wakes in a row
    CARD = "card"  # a proposal's card left waiting for days
    REMINDER = "reminder"  # one Hansen set (reminders.py): sent at its time, never judged by the policy


class Item(BaseModel):
    """One thing a wake could say."""

    kind: ItemKind
    key: str  # the same thing told twice has the same key
    source: str  # the module whose observation it is, or MAIN
    text: str
    since: str  # when it became true (an observation: when it was made)
    alert: bool = False
    ref: str | None = None  # the observation's id, the proposal's id, the module's name
    channel: str | None = None  # where it goes: a card goes to its own thread; None: home
    thread: str | None = None

    @classmethod
    def of(cls, obs: Observation, zone: tzinfo) -> Item:
        """The same summary from a module on the same day is one thing, and so are the SDK's error reports for it."""
        what = "" if obs.type in ERRORS else "/" + hashlib.sha1(obs.summary.encode()).hexdigest()[:12]
        return cls(
            kind=ItemKind.OBSERVE,
            key=f"observe/{obs.source}/{obs.type}{what}/{local_day(obs.ts, zone)}",
            source=obs.source,
            text=f"{obs.source}: {one_line(obs.summary, SUMMARY_SHOWN)}",
            since=obs.ts,
            alert=obs.severity_hint == Severity.ALERT,
            ref=obs.id,
        )


class Home(BaseModel):
    model_config = ConfigDict(frozen=True)  # a place: compared, and a key

    channel: str
    thread: str


class DownModule(BaseModel):
    since: str  # the first wake that saw it down; the next one that does tells it
    told: bool = False


class WakeState(BaseModel):
    day: str = ""  # the local date `sent` counts for
    sent: int = 0  # told today without being asked, alerts included
    held: list[Observation] = Field(default_factory=list)  # notices and alerts waiting for a good moment
    told: dict[str, str] = Field(default_factory=dict)  # item key -> when it was told
    alerts: dict[str, list[str]] = Field(default_factory=dict)  # module -> its alerts told in the last hour
    down: dict[str, DownModule] = Field(default_factory=dict)  # modules that should run and do not
    downvotes: dict[str, dict[str, str]] = Field(default_factory=dict)  # module -> message 👎'd -> when
    replies: dict[str, str] = Field(default_factory=dict)  # a message told -> the source it came from (votes)
    waiting: dict[str, Verdict] = Field(default_factory=dict)  # item key -> why it is held (traced when it changes)


class WakePolicy(BaseModel):
    every_s: float = Field(default=900.0, ge=0)  # 0: no timer (tests); a held item waits for the next wake
    quiet: tuple[time, time] | None = (time(23), time(8))
    budget: int = Field(default=3, ge=0)
    channels: tuple[str, ...] = ("telegram", "web")  # where Main may write first
    notice_delay_s: float = Field(default=120.0, ge=0)  # notices that come within this are one wake
    hold_s: float = 10 * 3600.0
    busy_s: float = 300.0  # Hansen wrote in the thread this recently: not now
    repeat_s: float = 20 * 3600.0
    alerts_per_hour: int = 1
    mute_after: int = 2  # 👎 in a week
    vote_days: int = 7
    card_after_s: float = 3 * 86400.0  # a card waiting this long is shown once more
    card_until_s: float = 14 * 86400.0  # and one older than this is left alone

    def is_quiet(self, local: time) -> bool:
        if self.quiet is None:
            return False
        start, end = self.quiet
        return start <= local < end if start < end else local >= start or local < end

    def tidy(self, state: WakeState, now: datetime, zone: tzinfo) -> WakeState:
        """A new day resets the count; what is too old to matter is let go."""
        day = now.astimezone(zone).date().isoformat()
        if state.day != day:
            state.day, state.sent = day, 0
        state.told = {k: t for k, t in state.told.items() if age_s(t, now) < self.repeat_s}
        state.alerts = {m: k for m, ts in state.alerts.items() if (k := [t for t in ts if age_s(t, now) < 3600])}
        week = self.vote_days * 86400
        state.downvotes = {
            m: kept
            for m, votes in state.downvotes.items()
            if (kept := {r: t for r, t in votes.items() if age_s(t, now) < week})
        }
        state.replies = dict(list(state.replies.items())[-REPLIES_KEPT:])
        return state

    def hold(self, state: WakeState, obs: Observation, zone: tzinfo) -> bool:
        """Keep a notice or an alert for the next wake: short, without its data. False when the same thing waits."""
        kept = obs.model_copy(update={"data": {}, "summary": cut(obs.summary, SUMMARY_SHOWN)})
        key = Item.of(kept, zone).key
        if any(Item.of(o, zone).key == key for o in state.held):
            return False
        state.held.append(kept)
        mine = [o for o in state.held if o.source == obs.source]
        if len(mine) > HELD_PER_SOURCE:
            state.held.remove(mine[0])
        state.held = state.held[-HELD_MAX:]
        return True

    def judge(self, item: Item, state: WakeState, now: datetime, zone: tzinfo, busy: bool) -> Verdict:
        votes = len(state.downvotes.get(item.source, {})) if item.source != MAIN else 0
        if votes >= self.mute_after:
            return Verdict.MUTED
        if item.kind == ItemKind.OBSERVE and age_s(item.since, now) > self.hold_s:
            return Verdict.EXPIRED
        if item.alert and not votes and len(state.alerts.get(item.source, [])) < self.alerts_per_hour:
            return Verdict.SENT  # an event, not a state: the same words an hour later are news again
        if item.key in state.told:
            return Verdict.REPEAT
        if self.is_quiet(now.astimezone(zone).time()):
            return Verdict.QUIET
        if busy:
            return Verdict.BUSY
        if state.sent >= self.budget:
            return Verdict.BUDGET
        return Verdict.SENT

    def record(self, state: WakeState, item: Item, verdict: Verdict, now: datetime, reply: str | None) -> None:
        """What a verdict leaves in the state."""
        if verdict.held:
            state.waiting[item.key] = verdict
            return
        state.waiting.pop(item.key, None)
        if item.kind == ItemKind.OBSERVE:
            state.held = [o for o in state.held if o.id != item.ref]
        if verdict != Verdict.SENT:
            return
        stamp = now.isoformat()
        state.sent += 1
        state.told[item.key] = stamp
        if item.alert:
            state.alerts.setdefault(item.source, []).append(stamp)
        if item.kind == ItemKind.DOWN and item.ref in state.down:
            state.down[item.ref].told = True
        if reply:
            state.replies[reply] = item.source

    def vote(self, state: WakeState, ref: str, vote: int, now: datetime) -> str | None:
        """A 👎 on a message a module's observation led to counts against that module, once per message; a 👍 clears
        its 👎s. Returns the module, or None when the message was not one of these."""
        source = state.replies.get(ref)
        if source is None or source == MAIN:
            return None
        if vote < 0:
            state.downvotes.setdefault(source, {})[ref] = now.isoformat()
        elif vote > 0:
            state.downvotes.pop(source, None)
        return source


class WakeOutcome(BaseModel):
    """One item of a trace.wake: what could be said, and what became of it."""

    kind: ItemKind
    source: str
    text: str
    verdict: Verdict
    ref: str | None = None
    reply_id: str | None = None  # the message it went out as


class WakeTrace(Envelope):
    source: str = MAIN
    reason: str  # timer | notice | alert | reminder
    items: list[WakeOutcome] = Field(default_factory=list)
    sent_today: int = 0
    budget: int = 0


class WakeStore:
    def __init__(self, kv: KV) -> None:
        self.kv = kv

    async def load(self) -> WakeState:
        raw = await self.kv.get(STATE_KEY)
        return WakeState.model_validate(raw) if raw is not None else WakeState()

    async def save(self, state: WakeState) -> None:
        await self.kv.put(STATE_KEY, state.model_dump(mode="json"))

    async def home(self) -> Home | None:
        raw = await self.kv.get(HOME_KEY)
        return Home.model_validate(raw) if raw is not None else None

    async def set_home(self, home: Home) -> None:
        await self.kv.put(HOME_KEY, home.model_dump())


def age_s(iso: str, now: datetime) -> float:
    """Seconds since `iso`; a time that does not read is taken as long ago."""
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return float("inf")
    return (now - (t if t.tzinfo else t.replace(tzinfo=UTC))).total_seconds()


def local_day(iso: str, zone: tzinfo) -> str:
    """The user's date of a time; empty when it does not read."""
    try:
        return datetime.fromisoformat(iso).astimezone(zone).date().isoformat()
    except ValueError:
        return ""


def since_local(iso: str, now: datetime, zone: tzinfo) -> str:
    """When something began, as Hansen reads it: 14:05, or Mon 14:05 for another day."""
    try:
        t = datetime.fromisoformat(iso).astimezone(zone)
    except ValueError:
        return "a while ago"
    return f"{t:%H:%M}" if t.date() == now.astimezone(zone).date() else f"{t:%a %H:%M}"


def day_of(iso: str, zone: tzinfo) -> str:
    """A card's day: Mon 11-09."""
    try:
        return f"{datetime.fromisoformat(iso).astimezone(zone):%a %m-%d}"
    except ValueError:
        return "earlier"
