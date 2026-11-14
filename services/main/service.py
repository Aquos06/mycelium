"""Main on the bus.

    sense.chat      {id, channel, thread, text}            -> recall, plan, reply on out.say (or out.ask), with
                                                              the blocks `show` made from a module's data
    sense.feedback  {ref, answer} | {ref, vote}            -> an answer continues the thread; a vote is traced
    brain.observe                                          -> a module's notice or alert wakes Main (wake.py): told
                                                              in the thread Hansen last wrote in, when the policy
                                                              lets it (quiet hours, a chat in progress, the budget)
    build.stage                                            -> out.progress in the thread that asked: one message
                                                              per build, changed in place as it goes (progress.py)
    build.done / build.failed                              -> told in the thread whose proposal started it; the
                                                              progress message says how it ended, after the reply

Every handled message ends in one trace.plan with the pack, the tool calls, the model usage and the
reply, linked by `cause` to the message that started it.

Growing a module: `propose_module` ends the turn like `ask`; Main stores the proposal (proposals.py), then
sends its card with Build it / Not now. A tap on Build it is handled here, not by the model: it calls
rpc.build.start under the thread's lock, so a double tap or an old card finds the proposal decided.
`change_module` is the same for a module the builder grew: a card with Change it / Not now, and a tap starts a
change build, which keeps the module running as it is until the new version deploys. `delete_module` sends a card
with Delete it / Keep it, and a tap deletes the module while it waits (rpc.build.remove): its data is copied aside
first and its code stays in git.

Waking: besides a module's notice or alert, a timer wakes Main every MAIN_WAKE_EVERY minutes to look for a module
that stopped running and a card left waiting for days. What it may say is decided in code (wake.py), never by the
model, and one trace.wake says what it told, held or dropped and why.

Each message is handled in its own task, so one slow turn never holds up the others; turns on the
same (channel, thread) take a lock, so a typed message and a button tap cannot interleave.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Coroutine
from datetime import UTC, date, datetime
from typing import Any, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError

from mycelium_sdk import (
    Bus,
    ChatMessage,
    CompletionReply,
    CompletionRequest,
    Envelope,
    Manifest,
    Message,
    NoAnswer,
    Observation,
    Refused,
    RequestSpec,
    Role,
    Severity,
    TextBlock,
    ToolUse,
    ask,
    kv_key,
    now_iso,
    validation_message,
)
from mycelium_sdk.blocks import Formatter
from mycelium_sdk.build import (
    BuildDone,
    BuildFailed,
    BuildMode,
    BuildRecord,
    BuildRef,
    BuildRequest,
    BuildStage,
    Removed,
    RemoveRequest,
    Stage,
    StartReply,
)
from mycelium_sdk.views import View, views_of

from .blocks import TurnData
from .progress import as_text, ended, running
from .prompt import planner_prompt
from .proposals import Proposal, ProposalKind, ProposalStatus, ProposalStore
from .schemas import (
    Ask,
    AskOutput,
    BuildOutcome,
    FeedbackTrace,
    LlmCall,
    ModuleInfo,
    Notify,
    PackSummary,
    PlanTrace,
    Progress,
    ProgressState,
    Say,
    SayOutput,
)
from .thread import Thread, ThreadStore, Turn, TurnCall
from .tools import (
    AskArgs,
    AskModuleArgs,
    ChangeArgs,
    DeleteArgs,
    ProposeArgs,
    RecallPayload,
    ToolContext,
    ToolOutcome,
    ToolRegistry,
    default_tools,
)
from .tools.lookup import SysList
from .wake import (
    MAIN,
    DownModule,
    Home,
    Item,
    ItemKind,
    Verdict,
    WakeOutcome,
    WakePolicy,
    WakeState,
    WakeStore,
    WakeTrace,
    age_s,
    day_of,
    since_local,
)

log = logging.getLogger("mycelium.main")

M = TypeVar("M", bound=BaseModel)

MODEL_DOWN_REPLY = "I can't reach my model right now, so I can't answer this yet. I kept your message."
MODEL_SLOW_REPLY = "My model took too long to answer this time, so I stopped. I kept your message: ask me again."
OUT_OF_ROUNDS = "planner did not finish"
BUILD_IT = "Build it"
CHANGE_IT = "Change it"
DELETE_IT = "Delete it"
NOT_NOW = "Not now"
KEEP_IT = "Keep it"  # Not now, on a deletion's card
TAPS = (BUILD_IT, CHANGE_IT, DELETE_IT, NOT_NOW, KEEP_IT)  # the answers a proposal's card can carry back
UNTOUCHED_AFTER = ("deploy",)  # a change that failed at deploy may have stopped the old version; before it, never
ERROR_SHOWN = 300  # characters of a builder error told in the chat; the build record has all of it
MAX_TOOL_RESULT_CHARS = 4000
BUS_MARGIN_S = 5.0  # the gateway enforces the timeout; Main waits a little longer for its clean error

# A reply that says something was saved when no `remember` went through: the model wrote the words without the call
# (the thread showed it "Logged: 152" often enough). Main asks once more before the reply goes out.
CLAIM = re.compile(
    r"\bI(?:'ve| have|'ll| will)? (?:also |just |now )?(?:saved|noted|remembered|logged|recorded|stored|written down"
    r"|made a note|added (?:it|that|this|them) to)\b"  # "I've saved", "I logged": first person, done
    r"|^(?:got it[,.!]? )?(?:saved|noted|logged|remembered|recorded)\b"  # "Saved: ...", "Noted." opening a line
    r"|\b(?:it's|it is|that's|that is|all|everything's|everything is) (?:saved|noted|logged|recorded|stored)\b"
    r"|\bI'll remember\b"
    r"|\b(?:got|have) (?:it|that|this|them) (?:all )?(?:saved|noted|logged|down)\b"  # "I've got it saved"
    r"|已記住|已记住|記下了|记下了|記住了|记住了|已記錄|已记录|已儲存|已保存|存好了|幫你記|帮你记",
    re.IGNORECASE | re.MULTILINE,
)  # not "nothing was saved", "I can remember it for you", or a module's own "logged 12 sessions"
WRITES = ("add", "log", "record", "save", "store", "set", "update", "put", "track")  # a module request that keeps
RECHECK = (
    "(A note from Main's code, not from Hansen.) Your reply says something was saved, but no `remember` or module "
    "write (like `add`) went through in this turn. If something from his message belongs in memory, call `remember` now. If a module that "
    "listens to sense.chat logged it, say which one. Then write your reply to Hansen again from the start, as if "
    "this note had not been sent, and do not mention it."
)


class MainService:
    def __init__(
        self,
        bus: Bus,
        store: ThreadStore,
        today: Callable[[], date] = date.today,
        tz: str = "Asia/Taipei",
        max_rounds: int = 4,
        recall_budget: int = 8,
        llm_timeout: float = 90.0,
        build_timeout: float = 30.0,
        delete_timeout: float = 150.0,
        tools: ToolRegistry | None = None,
        proposals: ProposalStore | None = None,
        currency: str = "TWD",
        wake: WakePolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.bus = bus
        self.store = store
        self.proposals = proposals or ProposalStore(store.kv)  # the same bucket as the threads
        self.today = today
        self.tz = tz
        try:
            self.zone = ZoneInfo(tz)  # the dates on the thread's earlier messages
        except (ZoneInfoNotFoundError, ValueError):
            log.warning("unknown time zone %r: the thread's dates are in UTC", tz)
            self.zone = ZoneInfo("UTC")
        self.currency = currency  # money in the blocks `show` puts under a reply
        self.max_rounds = max_rounds
        self.recall_budget = recall_budget
        self.llm_timeout = llm_timeout
        # rpc.build.start: the builder asks the supervisor and the coder before it answers (5 s each), the build
        # itself runs later
        self.build_timeout = build_timeout
        # rpc.build.remove: the deletion happens while the tap waits; the builder gives the supervisor 120 s for it
        self.delete_timeout = delete_timeout
        self._catch_up: asyncio.Task | None = None
        self.tools = tools or default_tools()
        self.ctx = ToolContext(bus=bus, recall_budget=recall_budget)
        self._tool_specs = self.tools.specs()
        self._tasks: set[asyncio.Task] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._deleting: set[str] = set()  # proposals whose deletion runs now, outside their thread's lock
        self.wake = wake or WakePolicy()
        self.wakes = WakeStore(store.kv)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._wake_lock = asyncio.Lock()  # one wake at a time: each reads and writes wake/state
        self._home: Home | None = None  # the thread Hansen last wrote in (wake/home), once read
        self._ticker: asyncio.Task | None = None
        self._notice_wake: asyncio.Task | None = None  # notices that come within notice_delay_s are one wake
        self._notice_pending = False  # a notice came that no wake has read yet

    async def start(self) -> None:
        await self.bus.connect()
        await self.bus.subscribe("sense.chat", self._dispatch(self.on_chat), queue="main")
        await self.bus.subscribe("sense.feedback", self._dispatch(self.on_feedback), queue="main")
        await self.bus.subscribe("brain.observe", self._dispatch(self.on_observe), queue="main")
        await self.bus.subscribe("build.stage", self._dispatch(self.on_stage), queue="main")
        await self.bus.subscribe("build.done", self._dispatch(self.on_build), queue="main")
        await self.bus.subscribe("build.failed", self._dispatch(self.on_build), queue="main")
        await self.bus.subscribe("sys.module.removed", self._dispatch(self.on_removed), queue="main")
        # builds that ended while Main was down; never holds up the start, and outside drain(): it may wait minutes
        self._catch_up = asyncio.create_task(self.catch_up())
        if self.wake.every_s:
            self._ticker = asyncio.create_task(self._tick())

    async def stop(self) -> None:
        """The timers end; what is in flight is drain()'s."""
        for task in (self._ticker, self._notice_wake, self._catch_up):
            if task is not None:
                task.cancel()

    # ---- dispatch ------------------------------------------------------------------------

    def _dispatch(self, fn: Callable[[Message], Coroutine[Any, Any, None]]):
        async def handler(msg: Message) -> None:
            self._spawn(self._run(fn, msg))  # return at once: NATS delivers one callback at a time

        return handler

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, fn: Callable[[Message], Coroutine[Any, Any, None]], msg: Message) -> None:
        try:
            await fn(msg)
        except Exception:  # a bad message must never kill Main
            log.exception("main handler failed on %s", msg.subject)

    async def drain(self) -> None:
        """Wait for every message in flight (tests, shutdown)."""
        while pending := [t for t in self._tasks if not t.done()]:  # done tasks leave the set a tick later
            await asyncio.gather(*pending, return_exceptions=True)

    def _lock(self, channel: str, thread: str) -> asyncio.Lock:
        return self._locks.setdefault(kv_key("thread", channel, thread), asyncio.Lock())

    # ---- handlers ------------------------------------------------------------------------

    async def on_chat(self, msg: Message) -> None:
        data = msg.data
        text = str(data.get("text") or "").strip()
        if not text:
            return
        channel = str(data.get("channel") or data.get("source") or "unknown")
        thread_id = str(data.get("thread") or data.get("chat_id") or "default")
        await self._at_home(channel, thread_id)
        async with self._lock(channel, thread_id):
            await self._turn(data, text, channel, thread_id)

    async def on_feedback(self, msg: Message) -> None:
        data = msg.data
        await self.bus.publish(
            "trace.feedback",
            Envelope.child_of(data, "main").into(
                FeedbackTrace,
                ref=data.get("ref"),
                vote=_vote_of(data.get("vote")),
                answer=data.get("answer"),
                channel=data.get("channel"),
                thread=data.get("thread"),
            ),
        )
        if (vote := _vote_of(data.get("vote"))) is not None and data.get("ref"):
            self._spawn(self._vote(str(data["ref"]), vote))  # never holds up an answer in the same message
        answer = str(data.get("answer") or "").strip()
        if not answer:
            return
        ref = str(data.get("ref") or "")
        if ref and answer in TAPS and (proposal := await self.proposals.by_card(ref)):
            async with self._lock(proposal.channel, proposal.thread):
                deleting = await self._decide(ref, answer, data)
            if deleting is not None:
                await self._delete_now(deleting, data)
            return
        await self.on_chat(Message(subject="sense.chat", data={**data, "text": answer}))

    # ---- waking ----------------------------------------------------------------------------

    async def on_observe(self, msg: Message) -> None:
        """A module's notice is held for a wake a little later, so the ones that come together are one; an alert
        wakes Main now. `info` is for the record and wakes nothing."""
        obs = _read(Observation, msg)
        if obs is None or obs.severity_hint == Severity.INFO or not obs.summary.strip():
            return
        if obs.source == MAIN:  # Main never observes: a module calling itself main would never be muted
            log.warning("an observation claims to be Main's (%s): ignored", obs.type)
            return
        async with self._wake_lock:
            state = await self.wakes.load()
            if not self.wake.hold(state, obs, self.zone):
                return  # the same thing is waiting already
            await self.wakes.save(state)
        if obs.severity_hint == Severity.ALERT or not self.wake.notice_delay_s:
            await self.wake_up(obs.severity_hint.value)
            return
        self._notice_pending = True
        if self._notice_wake is None or self._notice_wake.done():
            self._notice_wake = asyncio.create_task(self._notices())

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(self.wake.every_s)
            await self._safe_wake("timer")

    async def _notices(self) -> None:
        """One wake for the notices that come within notice_delay_s, and another for any that came while it ran."""
        while self._notice_pending:
            await asyncio.sleep(self.wake.notice_delay_s)
            self._notice_pending = False
            await self._safe_wake("notice")

    async def _safe_wake(self, reason: str) -> None:
        try:
            await self.wake_up(reason)
        except Exception:  # a wake that failed is tried again by the next one
            log.exception("wake (%s) failed", reason)

    async def wake_up(self, reason: str) -> None:
        """Look at what could be said now and say what the policy lets through. The timer also looks for modules
        that stopped running and cards left waiting; a notice or an alert wake only tells what is held."""
        async with self._wake_lock:
            now = self.clock()
            state = self.wake.tidy(await self.wakes.load(), now, self.zone)
            items = [Item.of(o, self.zone) for o in state.held]
            if reason == "timer":
                items += await self._down(state, now)
                items += await self._waiting_cards(now)
                looked = {i.key for i in items}
                state.waiting = {k: v for k, v in state.waiting.items() if k in looked}
            outcomes: list[WakeOutcome] = []
            news = False
            busy: dict[Home | None, bool] = {}  # once per place it would go
            for item in items:
                where = await self._where(item)
                if where not in busy:
                    busy[where] = await self._busy(where, now)
                verdict = self.wake.judge(item, state, now, self.zone, busy=busy[where])
                reply = None
                if verdict == Verdict.SENT:
                    try:
                        reply = await self._say_unasked(item)
                    except Exception:
                        log.exception("could not tell %s", item.key)
                        continue  # still held, or found again: the next wake tries it
                news = news or state.waiting.get(item.key) != verdict
                self.wake.record(state, item, verdict, now, reply)
                if reply:  # recorded as soon as it went out: a wake that stops later never tells it twice
                    await self.wakes.save(state)
                outcomes.append(
                    WakeOutcome(
                        kind=item.kind,
                        source=item.source,
                        text=item.text,
                        verdict=verdict,
                        ref=item.ref,
                        reply_id=reply,
                    )
                )
            await self.wakes.save(state)
        if news:
            trace = WakeTrace(reason=reason, items=outcomes, sent_today=state.sent, budget=self.wake.budget)
            await self.bus.publish("trace.wake", trace)

    async def _down(self, state: WakeState, now: datetime) -> list[Item]:
        """Modules that should be running (the registry says so) and whose container is not, at two wakes in a row: a
        restart or a deploy in between is not news. Told once until it runs again. A supervisor that does not answer
        says nothing about them, either way."""
        try:
            listed = await ask(self.bus, "rpc.sys.list", None, SysList, timeout=5.0)
        except (NoAnswer, Refused):
            return []
        down = {r.name: r.container for r in listed.modules if r.status == "running" and r.container != "running"}
        state.down = {n: d for n, d in state.down.items() if n in down}  # running again: a new stop is news again
        items = []
        for name, container in sorted(down.items()):
            seen = state.down.get(name)
            if seen is None:  # the first look that finds it down: the next one tells it
                state.down[name] = DownModule(since=now.isoformat())
                continue
            if seen.told:
                continue
            why = f"its container is {container}" if container else "it has no container"
            items.append(
                Item(
                    kind=ItemKind.DOWN,
                    key=f"down/{name}/{seen.since}",
                    source=MAIN,
                    text=(
                        f"{name} has stopped running ({why}) since about {since_local(seen.since, now, self.zone)}. "
                        "Its data is kept. You can start it again from its page in the app."
                    ),
                    since=seen.since,
                    ref=name,
                )
            )
        return items

    async def _waiting_cards(self, now: datetime) -> list[Item]:
        """A card to build or change a module that has waited days without a tap: shown once more, in its thread. A
        deletion is never pushed."""
        try:
            offered = await self.proposals.offered(limit=None)
        except Exception as e:
            log.info("could not read the proposals: %s", e)
            return []
        items = []
        for p in offered:
            if p.status != ProposalStatus.PROPOSED or p.is_delete or p.nudged or p.channel not in self.wake.channels:
                continue
            if not self.wake.card_after_s <= age_s(p.created, now) <= self.wake.card_until_s:
                continue
            what = f"The change to {p.name}" if p.is_change else f"The {p.name} module"
            yes, no = _choices(p)
            items.append(
                Item(
                    kind=ItemKind.CARD,
                    key=f"card/{p.id}",
                    source=MAIN,
                    text=(
                        f"{what} I offered on {day_of(p.created, self.zone)} is still waiting: {p.purpose}\n\n"
                        f"{yes}, or {no} to let it go."
                    ),
                    since=p.created,
                    ref=p.id,
                    channel=p.channel,
                    thread=p.thread,
                )
            )
        return items

    async def _busy(self, where: Home | None, now: datetime) -> bool:
        """Hansen is mid-conversation where it would go: a turn running there, or a message there just now."""
        if where is None:
            return False
        if self._lock(where.channel, where.thread).locked():
            return True
        thread = await self.store.load(where.channel, where.thread)
        last = next((t for t in reversed(thread.turns) if t.role == Role.USER), None)
        return last is not None and age_s(last.ts, now) < self.wake.busy_s

    async def _where(self, item: Item) -> Home | None:
        if item.channel and item.thread:
            return Home(channel=item.channel, thread=item.thread)
        if self._home is None:
            self._home = await self.wakes.home()
        return self._home

    async def _say_unasked(self, item: Item) -> str:
        """Tell it, and keep it in the thread so a reply to it is read with it. Returns the message's id."""
        if item.kind == ItemKind.CARD:
            async with self._lock(item.channel or "", item.thread or ""):
                p = await self.proposals.get(item.ref or "")  # read again under the lock: a tap may have decided it
                if p is None or p.status != ProposalStatus.PROPOSED or p.nudged:
                    raise LookupError(f"proposal {item.ref} is gone or decided")
                card = await self._tell(p, item.text, {}, offer_again=True)
                p.nudged = now_iso()
                await self.proposals.save(p)
            return card
        home = await self._where(item)
        if home is None:  # Hansen has written nowhere yet: the phone and the app's home screen still get it
            note = Notify(text=item.text)
            await self.bus.publish("out.notify", note)
            return note.id
        out = Envelope(source="main", cause=item.ref if item.kind == ItemKind.OBSERVE else None)
        await self.bus.publish("out.say", out.into(Say, channel=home.channel, thread=home.thread, text=item.text))
        # kept in the thread once a turn running there is done: an alert goes out now, never after the turn
        self._spawn(self._keep(home, Turn(role=Role.ASSISTANT, text=item.text, ts=out.ts, id=out.id)))
        return out.id

    async def _keep(self, where: Home, turn: Turn) -> None:
        async with self._lock(where.channel, where.thread):
            thread = await self.store.load(where.channel, where.thread)
            await self.store.append(thread, turn)

    async def _at_home(self, channel: str, thread: str) -> None:
        """Where Hansen writes is where Main writes first, on a channel that reaches Hansen (not mctl's)."""
        if channel not in self.wake.channels:
            return
        home = Home(channel=channel, thread=thread)
        if home == self._home:
            return
        self._home = home
        try:
            await self.wakes.set_home(home)
        except Exception:
            log.exception("could not keep the home thread")

    async def _vote(self, ref: str, vote: int) -> None:
        """A 👍 or 👎 on something Main told without being asked: it counts for the module that led to it."""
        async with self._wake_lock:
            state = await self.wakes.load()
            if self.wake.vote(state, ref, vote, self.clock()) is not None:
                await self.wakes.save(state)

    # ---- growing a module ------------------------------------------------------------------

    async def _decide(self, ref: str, answer: str, data: dict[str, Any]) -> Proposal | None:
        """A tap on a proposal's card, under its thread's lock. The model plays no part in this. A Delete it is
        returned, to run once the lock is let go (_delete_now)."""
        p = await self.proposals.by_card(ref)  # read again under the lock: a second tap sees what the first one did
        if p is None:
            return None
        offer_again = False
        if p.status != ProposalStatus.PROPOSED:
            reply = _already(p)
        elif p.id in self._deleting:
            reply = f"{p.name} is being deleted now. I'll tell you here when it's done."
        elif answer in (NOT_NOW, KEEP_IT):
            p.status, p.decided = ProposalStatus.DECLINED, now_iso()
            reply = _declined(p)
        elif answer != _choices(p)[0]:  # another card's yes: no app sends it, and it never builds or deletes
            return None
        elif p.is_delete:
            self._deleting.add(p.id)  # under the lock: a second tap from now on is told it is under way
            return p
        else:
            reply, offer_again = await self._start_build(p, data)
        await self.proposals.save(p)
        await self._tell(p, reply, data, answer=answer, offer_again=offer_again)
        return None

    async def _delete_now(self, p: Proposal, data: dict[str, Any]) -> None:
        """A Delete it, with the thread's lock let go while the module is copied and removed (seconds, or minutes
        behind a deploy): Hansen's messages there are answered meanwhile. What happened is said there after."""
        try:
            reply = await self._delete(p)
            async with self._lock(p.channel, p.thread):
                await self.proposals.save(p)
                await self._tell(p, reply, data, answer=DELETE_IT)
        finally:
            self._deleting.discard(p.id)

    async def _start_build(self, p: Proposal, data: dict[str, Any]) -> tuple[str, bool]:
        """What to say, and whether to send a fresh card: the apps take the buttons off a card once it is answered,
        so a start that did not happen needs a new one to try again."""
        call = BuildRequest(
            name=p.name,
            spec="" if p.is_change else p.spec,
            change=p.change if p.is_change else "",
            cause=data.get("id"),
            hops=int(data.get("hops") or 0),
            channel=p.channel,
            thread=p.thread,
        )
        try:
            started = await ask(self.bus, "rpc.build.start", call, StartReply, timeout=self.build_timeout)
        except NoAnswer:
            # no answer is not "nothing started": the builder may have queued it after Main stopped waiting
            if await self._adopt(p):
                return _building(p), False
            p.note = "the builder did not answer"
            return (
                f"The builder didn't answer in time. If it starts {p.name} anyway, I'll tell you here; "
                f"otherwise choose {CHANGE_IT if p.is_change else BUILD_IT} again."
            ), True
        except Refused as e:  # busy, coder not ready, name taken, or already started by a tap that timed out
            if await self._adopt(p):
                return _building(p), False
            p.note = str(e)
            verb = "change" if p.is_change else "start"
            return f"The builder won't {verb} {p.name}: {p.short_note()}", True
        p.status, p.build_id, p.decided, p.note = ProposalStatus.BUILDING, started.build_id, now_iso(), None
        return _building(p, started.position), False

    async def _delete(self, p: Proposal) -> str:
        """The deletion: the builder asks the supervisor to copy its data and remove it, then takes its folder out of
        GROWN_DIR. A deletion that did not happen is told with the builder's reason and not offered again on a card:
        what stopped it (a build of it, a hand-written module) is not undone by a second tap."""
        try:
            removed = await ask(
                self.bus, "rpc.build.remove", RemoveRequest(name=p.name), Removed, timeout=self.delete_timeout
            )
        except NoAnswer:
            if await self._gone(p.name):  # it went through; only the answer, with where things went, was late
                p.status, p.decided, p.note = ProposalStatus.DONE, now_iso(), None
                return (
                    f"Deleted {p.name}. The builder answered late, so I can't say what it kept: any data and code it "
                    "had are under names ending in -removed-<time> (a Docker volume, a git tag)."
                )
            p.status, p.decided, p.note = ProposalStatus.FAILED, now_iso(), "the builder did not answer"
            return f"The builder didn't answer in time, so {p.name} may be deleted only partly. Ask me again to finish."
        except Refused as e:
            p.status, p.decided, p.note = ProposalStatus.FAILED, now_iso(), str(e)
            return f"I couldn't delete {p.name}: {p.short_note()}"
        p.status, p.decided, p.note = ProposalStatus.DONE, now_iso(), None
        return _deleted(removed)

    async def _gone(self, name: str) -> bool:
        """Neither listed by the supervisor nor a folder in either root: a deletion whose answer did not come in time
        went through."""
        try:
            listed = await ask(self.bus, "rpc.sys.list", None, SysList, timeout=5.0)
        except (NoAnswer, Refused):
            return False
        return name not in listed.names()

    async def on_removed(self, msg: Message) -> None:
        """A module deleted from anywhere (its page, mctl, a card): a card that still asks to delete it is stale, and a
        tap on it later must never delete a module grown again under its name. From now on it reads as deleted."""
        name = str(msg.data.get("name") or "")
        for p in await self.proposals.asking_to_delete(name):
            async with self._lock(p.channel, p.thread):
                fresh = await self.proposals.get(p.id)
                if fresh is None or fresh.status != ProposalStatus.PROPOSED or fresh.id in self._deleting:
                    continue  # decided meanwhile, or this is its own deletion: that one says what happened
                fresh.status, fresh.decided, fresh.note = ProposalStatus.DONE, now_iso(), "deleted elsewhere"
                await self.proposals.save(fresh)

    async def _adopt(self, p: Proposal) -> bool:
        """A build of this proposal the builder has although its start went unanswered: same name, same thread."""
        try:
            listed = await self.bus.request("rpc.build.list", {"limit": 20}, timeout=5.0)
            for b in listed.get("builds") or []:
                if b.get("name") != p.name or b.get("status") not in ("queued", "building"):
                    continue
                record = await self.bus.request("rpc.build.get", BuildRef(build_id=str(b.get("id"))), timeout=5.0)
                if (record.get("channel"), record.get("thread")) == (p.channel, p.thread):
                    p.status, p.build_id, p.decided, p.note = ProposalStatus.BUILDING, str(b["id"]), now_iso(), None
                    return True
        except Exception as e:
            log.info("could not check the builder for %s: %s", p.name, e)
        return False

    async def on_stage(self, msg: Message) -> None:
        """A build that a thread asked for has moved on: its progress message there says where it is now. Rendered
        from the event alone (it carries every round so far), so there is nothing to look up and nothing to lose."""
        ev = _read(BuildStage, msg)
        if ev is None or not ev.channel or not ev.thread:
            return
        async with self._lock(ev.channel, ev.thread):  # the tap that started it says "Building ..." first
            await self._show(ev, Envelope.child_of(msg.data, "main"))

    async def _show(self, ev: BuildStage | BuildDone | BuildFailed, out: Envelope) -> None:
        """The build's progress message, in the thread that asked for it, as `ev` has it. Never fails its caller:
        a message that did not go out is replaced by the next one, and the end is said in the thread anyway."""
        if not ev.channel or not ev.thread:
            return
        if isinstance(ev, BuildStage):
            state, (title, steps) = ProgressState.RUNNING, running(ev)
        else:
            state = ProgressState.DONE if isinstance(ev, BuildDone) else ProgressState.FAILED
            title, steps = ended(ev)
        card = out.into(
            Progress,
            channel=ev.channel,
            thread=ev.thread,
            ref=ev.build_id,
            seq=ev.seq,
            title=title,
            state=state,
            steps=steps,
            text=as_text(title, steps, self.zone),
        )
        try:
            await self.bus.publish("out.progress", card)
        except Exception:
            log.exception("could not show the progress of build %s", ev.build_id)

    async def on_build(self, msg: Message) -> None:
        """build.done / build.failed: told in the thread whose proposal started it (other builds, mctl's, are not
        Main's to tell), and its progress message, if a thread asked for it, ends however the proposal stands."""
        ev = _read(BuildDone if msg.subject == "build.done" else BuildFailed, msg)
        if ev is None or not ev.channel or not ev.thread:
            return
        async with self._lock(ev.channel, ev.thread):  # the tap that started it holds this lock until saved
            try:
                p = await self.proposals.by_build(ev.build_id)
                if p is None:  # its start went unanswered at the tap: the latest proposal of that name, in this thread
                    latest = await self.proposals.by_name(ev.name)
                    if (
                        latest
                        and not latest.is_delete
                        and latest.status == ProposalStatus.PROPOSED
                        and (latest.channel, latest.thread) == (ev.channel, ev.thread)
                    ):
                        latest.status, latest.build_id = ProposalStatus.BUILDING, ev.build_id
                        p = latest
                if p is not None and p.status == ProposalStatus.BUILDING:
                    await self._finish(p, BuildOutcome.of(ev), msg.data)
            finally:
                await self._show(ev, Envelope.child_of(msg.data, "main"))

    async def catch_up(self, attempts: int = 20, wait: float = 30.0) -> None:
        """Builds that ended while Main was not listening: tell their threads. The builder may come up after Main
        (compose starts them together), so this tries again until it answers."""
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(wait)
            try:
                if await self._catch_up_once():
                    return
            except Exception:
                log.exception("catch-up failed")
        log.warning("catch-up: the builder did not answer; builds that end from now on are still told")

    async def _catch_up_once(self) -> bool:
        """False when the builder did not answer, so catch_up tries again later."""
        for p in await self.proposals.building():
            try:
                reply = await self.bus.request("rpc.build.get", BuildRef(build_id=p.build_id or "?"), timeout=5.0)
            except Exception:
                return False
            if reply.get("ok"):
                try:
                    ev = BuildRecord.model_validate(reply).ended()
                except ValidationError as e:
                    log.warning("build %s: its record does not read: %s", p.build_id, validation_message(e))
                    continue
                if ev is None:  # still queued or building: its build.done/failed will come
                    continue
                outcome = BuildOutcome.of(ev)
            elif "no build" in str(reply.get("error")):  # it answers, but lost the record: it will never report
                outcome = BuildOutcome(
                    build_id=p.build_id or "", done=False, stage="unknown", error="the builder has no record of it"
                )
                ev = _lost(p, outcome)
            else:
                return False
            async with self._lock(p.channel, p.thread):
                fresh = await self.proposals.get(p.id)
                if fresh is not None and fresh.status == ProposalStatus.BUILDING:
                    try:
                        await self._finish(fresh, outcome, {})
                    finally:
                        await self._show(ev, Envelope(source="main"))  # a record is not an event to be caused by
        return True

    async def _finish(self, p: Proposal, outcome: BuildOutcome, data: dict[str, Any]) -> None:
        """Say how it ended, in the proposal's thread."""
        if outcome.done:
            p.status = ProposalStatus.DONE
            version = f" (version {outcome.version})" if outcome.version else ""
            reply = (
                f"{p.name} is changed and running{version}, with its data kept. Ask me about it any time."
                if p.is_change
                else f"{p.name} is built and running{version}. Ask me about it any time."
            )
        else:
            p.status = ProposalStatus.FAILED
            p.note = f"{outcome.stage or 'unknown stage'}: {outcome.error or 'no error given'}"
            what = "Changing" if p.is_change else "Building"
            reply = f"{what} {p.name} failed at {outcome.stage or 'an unknown stage'}: {(outcome.error or '')[:ERROR_SHOWN]}"
            if p.is_change and outcome.stage not in UNTOUCHED_AFTER:
                reply += f"\n\n{p.name} still runs as it was{f' (version {p.base_version})' if p.base_version else ''}."
        await self.proposals.save(p)
        await self._tell(p, reply, data)

    async def _tell(
        self, p: Proposal, text: str, data: dict[str, Any], answer: str | None = None, offer_again: bool = False
    ) -> str:
        """Say it in the proposal's thread and keep it there, with the tap that led to it if there was one.
        With offer_again, it goes out as a fresh card for the same proposal (linked before it is sent). Returns the
        message's id."""
        out = Envelope.child_of(data, "main") if data else Envelope(source="main")
        if offer_again:
            await self.proposals.add_card(out.id, p)
            choices = _choices(p)
            card = out.into(Ask, channel=p.channel, thread=p.thread, text=text, choices=choices, ref=out.id)
            await self.bus.publish("out.ask", card)
            saved = f"{text}\n[choices: {' / '.join(choices)}]"
        else:
            await self.bus.publish("out.say", out.into(Say, channel=p.channel, thread=p.thread, text=text))
            saved = text
        thread = await self.store.load(p.channel, p.thread)
        turns = (
            [Turn(role=Role.USER, text=answer, ts=str(data.get("ts") or out.ts), id=data.get("id"))] if answer else []
        )
        await self.store.append(thread, *turns, Turn(role=Role.ASSISTANT, text=saved, ts=out.ts, id=out.id))
        return out.id

    # ---- one turn ------------------------------------------------------------------------

    async def _turn(self, data: dict[str, Any], text: str, channel: str, thread_id: str) -> None:
        cause = data.get("id")
        t0 = time.monotonic()

        thread = await self.store.load(channel, thread_id)
        (pack, recall_error), modules, offered = await asyncio.gather(
            self._recall(text), self._modules(), self._offered()
        )
        # the tools see this turn's modules: a call to one that is not running is refused at once
        turn = TurnData(
            formatter=Formatter(currency=self.currency, zone=self.zone, today=self.today()),
            views={m.name: m.views for m in modules or [] if m.status == "running" and m.views},
        )
        ctx = self.ctx.model_copy(
            update={
                "modules": None if modules is None else {m.name: _actions(m) for m in modules if m.status == "running"},
                "turn": turn,  # its own: what this turn's modules answered, and what `show` put on screen
            }
        )
        modules = modules or []
        prompt = planner_prompt(
            self.today(), self.tz, channel, text, pack, modules, recall_error, offered, thread=thread_id
        )
        gone = _gone_since(thread, offered, modules, channel, thread_id) if modules else ""
        messages = [*thread.messages(self.zone), ChatMessage(role=Role.USER, content=gone + prompt.user)]

        tool_log: list[ToolOutcome] = []
        llm_calls: list[LlmCall] = []
        reply_text = ""
        asked: AskArgs | None = None
        proposed: ProposeArgs | ChangeArgs | DeleteArgs | None = None
        base_version: str | None = None  # a change or a deletion: the module's version when it was asked
        error: str | None = None
        claim_check = False

        for _round in range(self.max_rounds):
            request = CompletionRequest(
                slot="planner",
                system=prompt.system,
                messages=messages,
                tools=self._tool_specs,
                cause=cause,
                hops=int(data.get("hops") or 0),
                timeout=self.llm_timeout,
                stream=True,  # the gateway publishes the text on stream.llm as it is written; the web app shows it
            )
            try:
                r = await ask(self.bus, "rpc.llm.complete", request, CompletionReply, self.llm_timeout + BUS_MARGIN_S)
            except NoAnswer as e:
                error = f"gateway unreachable: {e}"
                break
            except Refused as e:
                error = str(e)
                break
            llm_calls.append(LlmCall(model=r.model, usage=r.usage, cost_usd=r.cost_usd))
            if not r.tool_calls:
                reply_text = r.text.strip()  # reasoning models lead with blank lines
                if not claim_check and _round + 1 < self.max_rounds and _unbacked_claim(reply_text, tool_log, modules):
                    claim_check = True  # once: asked again, it either calls remember or says it plainly
                    messages.append(ChatMessage(role=Role.ASSISTANT, content=reply_text))
                    messages.append(ChatMessage(role=Role.USER, content=RECHECK))
                    continue
                break

            content: list[TextBlock | ToolUse] = [TextBlock(text=r.text)] if r.text else []
            content += [ToolUse(id=c.id, name=c.name, input=c.input) for c in r.tool_calls]
            messages.append(ChatMessage(role=Role.ASSISTANT, content=content))

            results = []
            for c in r.tool_calls:
                outcome = await self.tools.call(c.name, c.input, ctx)
                if asked is None and proposed is None:  # the first valid `ask` or proposal ends the turn
                    if isinstance(outcome.args, AskArgs):
                        asked = outcome.args
                    elif isinstance(outcome.args, ProposeArgs | ChangeArgs | DeleteArgs) and outcome.ok:  # not refused
                        proposed = outcome.args
                        base_version = outcome.result.get("version")
                tool_log.append(outcome)
                results.append(outcome.tool_result(c.id, MAX_TOOL_RESULT_CHARS))
            messages.append(ChatMessage(role=Role.USER, content=results))
            if asked or proposed:
                reply_text = r.text.strip()  # reasoning models lead with blank lines
                break
        else:
            error = f"{OUT_OF_ROUNDS} in {self.max_rounds} rounds"

        out = Envelope.child_of(data, "main")
        output: SayOutput | AskOutput
        blocks = [] if error else turn.blocks  # a turn that failed says so, without half its answer
        if proposed and not error:  # stored before its card goes out: the tap finds it by the card's id
            proposal = Proposal(
                id=out.id, name=proposed.name, purpose="", channel=channel, thread=thread_id, cause=cause
            )
            if isinstance(proposed, ChangeArgs):
                proposal.kind, proposal.purpose, proposal.change = (
                    ProposalKind.CHANGE,
                    proposed.summary(),
                    proposed.text(),
                )
                proposal.base_version = base_version
                card = AskArgs(text=proposed.card(base_version), choices=_choices(proposal))
            elif isinstance(proposed, DeleteArgs):
                proposal.kind, proposal.base_version = ProposalKind.DELETE, base_version
                card = AskArgs(text=proposed.card(base_version), choices=_choices(proposal))
            else:
                proposal.purpose, proposal.spec = proposed.purpose, proposed.spec()
                card = AskArgs(text=proposed.card(), choices=_choices(proposal))
            try:
                await self.proposals.create(proposal)
                asked = card
            except Exception as e:  # no card without its proposal stored, but Hansen still gets a reply
                log.exception("could not store the proposal for %s", proposed.name)
                what = {ChangeArgs: "a change to ", DeleteArgs: "the deletion of "}.get(
                    type(proposed), "a module for this "
                )
                reply_text = f"I drafted {what}({proposed.name}) but couldn't save it ({type(e).__name__}), "
                reply_text += "so I can't offer it right now. Ask me again in a moment."
                proposed = None
        if asked and not error:
            question = "\n\n".join(s for s in (reply_text, asked.text) if s)
            await self.bus.publish(
                "out.ask",
                out.into(
                    Ask,
                    channel=channel,
                    thread=thread_id,
                    text=question,
                    choices=asked.choices,
                    ref=out.id,
                    blocks=blocks,
                ),
            )
            saved = f"{question}\n[choices: {' / '.join(asked.choices)}]"
            output = AskOutput(ask=asked)
        else:
            if error or not reply_text:
                reply_text = _failed_reply(error, tool_log) if error else "(no reply)"
            await self.bus.publish(
                "out.say", out.into(Say, channel=channel, thread=thread_id, text=reply_text, blocks=blocks)
            )
            saved = reply_text
            output = SayOutput(say=reply_text)

        await self.store.append(
            thread,
            Turn(role=Role.USER, text=text, ts=str(data.get("ts") or out.ts), id=cause),
            Turn(role=Role.ASSISTANT, text=saved, ts=out.ts, id=out.id, calls=_kept(tool_log)),
        )
        await self.bus.publish(
            "trace.plan",
            Envelope.child_of(data, "main").into(
                PlanTrace,
                channel=channel,
                thread=thread_id,
                input=text,
                pack=PackSummary.from_reply(pack),
                recall_error=recall_error,
                modules=[m.name for m in modules],
                tools=tool_log,
                llm_calls=llm_calls,
                cost_usd=round(sum(c.cost_usd for c in llm_calls), 6),
                rounds=len(llm_calls),
                output=output,
                reply_id=out.id,
                proposal=proposed.name if proposed and not error else None,
                claim_check=claim_check,
                error=error,
                latency_ms=int((time.monotonic() - t0) * 1000),
            ),
        )

    # ---- context -------------------------------------------------------------------------

    async def _recall(self, text: str) -> tuple[dict[str, Any] | None, str | None]:
        try:
            payload = RecallPayload(query=text, budget=self.recall_budget)
            reply = await self.bus.request("rpc.memory.recall", payload, timeout=5.0)
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
        if not reply.get("ok"):
            return None, str(reply.get("error") or "recall failed")
        return reply, None

    async def _offered(self) -> list[Proposal]:
        try:
            return await self.proposals.offered()
        except Exception as e:  # the prompt goes without the list rather than the turn failing
            log.info("could not read the proposals: %s", e)
            return []

    async def _modules(self) -> list[ModuleInfo] | None:
        """Every module the supervisor knows, running or not; None when it did not answer (then nobody knows)."""
        try:
            reply = await self.bus.request("rpc.sys.list", {}, timeout=2.0)
        except Exception:
            return None
        out: list[ModuleInfo] = []
        grown = {str(n) for n in reply.get("grown") or []}
        for row in reply.get("modules") or []:
            manifest = row.get("manifest") or {}
            name = str(row.get("name") or manifest.get("name") or "")
            if not name:
                continue
            out.append(
                ModuleInfo(
                    name=name,
                    purpose=str(manifest.get("purpose") or ""),
                    requests=[f"{name}.{a}" for a in manifest.get("requests") or []],
                    listens=[str(s) for s in manifest.get("subscribes") or []],
                    specs=_specs(name, manifest.get("request_specs")),
                    status=str(row.get("status") or "running"),
                    version=str(row.get("version") or manifest.get("version") or ""),
                    grown=name in grown,
                    views=_views(name, manifest),
                )
            )
        return out


def _specs(name: str, raw: Any) -> dict[str, RequestSpec]:
    """A manifest's described requests, as `<module>.<action>`; one that does not validate is left out (the
    request is still listed, only undescribed), so a module's bad description never costs Main its module list."""
    out: dict[str, RequestSpec] = {}
    for action, spec in (raw or {}).items() if isinstance(raw, dict) else []:
        try:
            out[f"{name}.{action}"] = RequestSpec.model_validate(spec)
        except ValueError:
            log.info("module %s: request %s has a description Main cannot read", name, action)
    return out


def _views(name: str, manifest: Any) -> dict[str, View]:
    """A manifest's declared views that can be shown; a manifest that does not read, or a view that cannot be shown
    (a request it lacks, one that writes), is left out: Main shows its data by source instead."""
    try:
        m = Manifest.model_validate({**manifest, "name": name}) if isinstance(manifest, dict) else None
    except ValueError:
        return {}
    return views_of(m) if m is not None else {}


def _failed_reply(error: str, tools: list[ToolOutcome]) -> str:
    """Say what went wrong: steps used up (and the last step that failed), a model too slow, or one not reached."""
    if error.startswith(OUT_OF_ROUNDS):
        failed = [o for o in tools if not o.ok]
        why = f" The last thing that went wrong: {str(failed[-1].result.get('error'))[:200]}" if failed else ""
        return f"I couldn't finish this: I used all my steps without getting there.{why} I kept your message."
    return MODEL_SLOW_REPLY if "timed out" in error or "timeout" in error.lower() else MODEL_DOWN_REPLY


def _gone_since(
    thread: Thread, offered: list[Proposal], modules: list[ModuleInfo], channel: str, thread_id: str
) -> str:
    """A note before Hansen's message when a module this chat built or used has stopped running since: the thread
    still says "expenses is built and running", and the model believes the thread over the module list. Said in
    the newest message, where it weighs most; never kept in the thread."""
    used = {  # modules that answered here; a call refused because it never ran says nothing about now
        str(c.input.get("module"))
        for t in thread.turns
        for c in t.calls
        if c.name == "ask_module" and c.result.startswith('{"ok": true')
    }
    built = {  # a deletion done here is no module that stopped: the thread says it was deleted
        p.name
        for p in offered
        if not p.is_delete and p.status == ProposalStatus.DONE and (p.channel, p.thread) == (channel, thread_id)
    }
    status = {m.name: m.status for m in modules}
    gone = sorted(n for n in used | built if status.get(n, "gone") != "running")
    if not gone:
        return ""
    names = ", ".join(f"{n} ({status.get(n, 'gone')})" for n in gone)
    return (
        f"(A note from Main's code, not from Hansen: since earlier in this chat, these modules stopped running: "
        f"{names}. Earlier messages saying they run are out of date; only the modules under Modules run now.)\n\n"
    )


def _actions(m: ModuleInfo) -> list[str]:
    """`expenses.add` -> `add`: the names a module answers on."""
    return [r.removeprefix(f"{m.name}.") for r in m.requests]


def _unbacked_claim(text: str, tools: list[ToolOutcome], modules: list[ModuleInfo]) -> bool:
    """The reply says something was saved, nothing that saves went through (`remember`, a module's `add`), and it
    names no module that hears the chat (one that logged the message itself, as the policy asks it to say)."""
    if not CLAIM.search(text) or any(_kept_something(o) for o in tools):
        return False
    lowered = text.lower()
    return not any(m.name.lower() in lowered for m in modules if "sense.chat" in m.listens)


def _kept_something(o: ToolOutcome) -> bool:
    """A call that saved something: `remember`, or a module request that writes (`expenses.add`)."""
    if not o.ok:
        return False
    if o.name == "remember":
        return True
    action = o.args.action if isinstance(o.args, AskModuleArgs) else ""
    return o.name == "ask_module" and re.split(r"[-_]", action)[0] in WRITES


def _kept(tools: list[ToolOutcome]) -> list[TurnCall]:
    """The calls a turn keeps in its thread: those Main accepted (a rejected one taught nothing worth repeating)."""
    return [TurnCall.of(o.name, o.input, o.result) for o in tools if o.args is not None]


def _choices(p: Proposal) -> list[str]:
    """A proposal's card: its yes first."""
    if p.is_delete:
        return [DELETE_IT, KEEP_IT]
    return [CHANGE_IT if p.is_change else BUILD_IT, NOT_NOW]


def _declined(p: Proposal) -> str:
    if p.is_delete:
        return f"OK, I'll keep {p.name}. Ask me again whenever you want it gone."
    if p.is_change:
        return f"OK, I'll leave {p.name} as it is. Ask me again whenever you want the change."
    return f"OK, I won't build {p.name}. Ask me again whenever you want it."


def _deleted(r: Removed) -> str:
    """What went where: the data copy and the tag are how it comes back."""
    kept = [f"its data in {r.data}"] if r.data else []
    kept += [f"its code in git as {r.tag}"] if r.tag else []
    if not kept:
        return f"Deleted {r.name}."
    return f"Deleted {r.name}. I kept {' and '.join(kept)}, in case you want it back."


def _already(p: Proposal) -> str:
    """A tap on a card that was decided already: a second tap, or an old card."""
    if p.is_delete:
        match p.status:
            case ProposalStatus.DECLINED:
                return f"You chose to keep {p.name}. Ask me again if you want it gone now."
            case ProposalStatus.DONE:
                return f"{p.name} is already deleted."
            case _:
                return f"Deleting {p.name} didn't work ({p.short_note()}). Ask me to delete it again."
    if p.is_change:
        match p.status:
            case ProposalStatus.DECLINED:
                return f"You chose to leave {p.name} as it is. Ask me again if you want the change now."
            case ProposalStatus.BUILDING:
                return f"{p.name} is already being changed. I'll tell you here when the new version runs."
            case ProposalStatus.DONE:
                return f"{p.name} is already changed and running."
            case _:
                return f"Changing {p.name} failed ({p.short_note()}). Ask me to change it again."
    match p.status:
        case ProposalStatus.DECLINED:
            return f"You chose not to build {p.name}. Ask me again if you want it now."
        case ProposalStatus.BUILDING:
            return f"{p.name} is already being built. I'll tell you here when it's running."
        case ProposalStatus.DONE:
            return f"{p.name} is already built and running."
        case _:
            return f"Building {p.name} failed ({p.short_note()}). Ask me to propose it again."


def _building(p: Proposal, position: int = 0) -> str:
    ahead = f", after {position} other build{'s' if position > 1 else ''}" if position else ""
    if p.is_change:
        return f"Changing {p.name}{ahead}. It runs as it is until the new version is ready; I'll tell you here."
    return f"Building {p.name}{ahead}. I'll tell you here when it's running."


def _vote_of(raw: Any) -> int | None:
    """A vote as a number: 1, -1; None for anything else (a channel that sends "up" never breaks the answer)."""
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read(model: type[M], msg: Message) -> M | None:
    """An event as the model it should be; None (and a line in the log) when it is not."""
    try:
        return model.model_validate(msg.data)
    except ValidationError as e:
        log.warning("%s does not read as %s: %s", msg.subject, model.__name__, validation_message(e))
        return None


def _lost(p: Proposal, outcome: BuildOutcome) -> BuildFailed:
    """The end of a build the builder has no record of, for its progress message: stopped, nothing more known."""
    return BuildFailed(
        build_id=outcome.build_id,
        name=p.name,
        coder="",
        mode=BuildMode.CHANGE if p.is_change else BuildMode.NEW,
        channel=p.channel,
        thread=p.thread,
        rounds=0,
        seconds=0.0,
        stage=Stage.RESTART,  # not a step on the card: it reads "Stopped: <error>"
        error=outcome.error or "the builder has no record of it",
        base_version=p.base_version,
    )
