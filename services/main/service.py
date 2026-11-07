"""Main on the bus.

    sense.chat      {id, channel, thread, text}            -> recall, plan, reply on out.say (or out.ask), with
                                                              the blocks `show` made from a module's data
    sense.feedback  {ref, answer} | {ref, vote}            -> an answer continues the thread; a vote is traced
    brain.observe                                          -> v0: logged only (the gate comes with the snapshot)
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
change build, which keeps the module running as it is until the new version deploys.

Each message is handled in its own task, so one slow turn never holds up the others; turns on the
same (channel, thread) take a lock, so a typed message and a button tap cannot interleave.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Coroutine
from datetime import date
from typing import Any, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ValidationError

from mycelium_sdk import (
    Bus,
    ChatMessage,
    CompletionReply,
    CompletionRequest,
    Envelope,
    Message,
    NoAnswer,
    Refused,
    RequestSpec,
    Role,
    TextBlock,
    ToolUse,
    ask,
    kv_key,
    now_iso,
    validation_message,
)
from mycelium_sdk.build import (
    BuildDone,
    BuildFailed,
    BuildMode,
    BuildRecord,
    BuildRef,
    BuildRequest,
    BuildStage,
    Stage,
    StartReply,
)

from .blocks import Formatter, TurnData
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
    ProposeArgs,
    RecallPayload,
    ToolContext,
    ToolOutcome,
    ToolRegistry,
    default_tools,
)

log = logging.getLogger("mycelium.main")

M = TypeVar("M", bound=BaseModel)

MODEL_DOWN_REPLY = "I can't reach my model right now, so I can't answer this yet. I kept your message."
MODEL_SLOW_REPLY = "My model took too long to answer this time, so I stopped. I kept your message: ask me again."
OUT_OF_ROUNDS = "planner did not finish"
BUILD_IT = "Build it"
CHANGE_IT = "Change it"
NOT_NOW = "Not now"
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
        tools: ToolRegistry | None = None,
        proposals: ProposalStore | None = None,
        currency: str = "TWD",
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
        self._catch_up: asyncio.Task | None = None
        self.tools = tools or default_tools()
        self.ctx = ToolContext(bus=bus, recall_budget=recall_budget)
        self._tool_specs = self.tools.specs()
        self._tasks: set[asyncio.Task] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        await self.bus.connect()
        await self.bus.subscribe("sense.chat", self._dispatch(self.on_chat), queue="main")
        await self.bus.subscribe("sense.feedback", self._dispatch(self.on_feedback), queue="main")
        await self.bus.subscribe("brain.observe", self._dispatch(self.on_observe), queue="main")
        await self.bus.subscribe("build.stage", self._dispatch(self.on_stage), queue="main")
        await self.bus.subscribe("build.done", self._dispatch(self.on_build), queue="main")
        await self.bus.subscribe("build.failed", self._dispatch(self.on_build), queue="main")
        # builds that ended while Main was down; never holds up the start, and outside drain(): it may wait minutes
        self._catch_up = asyncio.create_task(self.catch_up())

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
        async with self._lock(channel, thread_id):
            await self._turn(data, text, channel, thread_id)

    async def on_feedback(self, msg: Message) -> None:
        data = msg.data
        await self.bus.publish(
            "trace.feedback",
            Envelope.child_of(data, "main").into(
                FeedbackTrace,
                ref=data.get("ref"),
                vote=data.get("vote"),
                answer=data.get("answer"),
                channel=data.get("channel"),
                thread=data.get("thread"),
            ),
        )
        answer = str(data.get("answer") or "").strip()
        if not answer:
            return
        ref = str(data.get("ref") or "")
        if ref and answer in (BUILD_IT, CHANGE_IT, NOT_NOW) and (proposal := await self.proposals.by_card(ref)):
            async with self._lock(proposal.channel, proposal.thread):
                await self._decide(ref, answer, data)
            return
        await self.on_chat(Message(subject="sense.chat", data={**data, "text": answer}))

    async def on_observe(self, msg: Message) -> None:
        log.debug("observe (v0: log only): %s", msg.data.get("summary"))

    # ---- growing a module ------------------------------------------------------------------

    async def _decide(self, ref: str, answer: str, data: dict[str, Any]) -> None:
        """A tap on a proposal's card, under its thread's lock. The model plays no part in this."""
        p = await self.proposals.by_card(ref)  # read again under the lock: a second tap sees what the first one did
        if p is None:
            return
        offer_again = False
        if p.status != ProposalStatus.PROPOSED:
            reply = _already(p)
        elif answer == NOT_NOW:
            p.status, p.decided = ProposalStatus.DECLINED, now_iso()
            reply = (
                f"OK, I'll leave {p.name} as it is. Ask me again whenever you want the change."
                if p.is_change
                else f"OK, I won't build {p.name}. Ask me again whenever you want it."
            )
        else:
            reply, offer_again = await self._start_build(p, data)
        await self.proposals.save(p)
        await self._tell(p, reply, data, answer=answer, offer_again=offer_again)

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
    ) -> None:
        """Say it in the proposal's thread and keep it there, with the tap that led to it if there was one.
        With offer_again, it goes out as a fresh card for the same proposal (linked before it is sent)."""
        out = Envelope.child_of(data, "main") if data else Envelope(source="main")
        if offer_again:
            await self.proposals.add_card(out.id, p)
            choices = [CHANGE_IT if p.is_change else BUILD_IT, NOT_NOW]
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

    # ---- one turn ------------------------------------------------------------------------

    async def _turn(self, data: dict[str, Any], text: str, channel: str, thread_id: str) -> None:
        cause = data.get("id")
        t0 = time.monotonic()

        thread = await self.store.load(channel, thread_id)
        (pack, recall_error), modules, offered = await asyncio.gather(
            self._recall(text), self._modules(), self._offered()
        )
        # the tools see this turn's modules: a call to one that is not running is refused at once
        turn = TurnData(formatter=Formatter(currency=self.currency, zone=self.zone, today=self.today()))
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
        proposed: ProposeArgs | ChangeArgs | None = None
        base_version: str | None = None  # a change: the module's version when it was drafted
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
                    elif isinstance(outcome.args, ProposeArgs | ChangeArgs) and outcome.ok:  # not when refused
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
                card = AskArgs(text=proposed.card(base_version), choices=[CHANGE_IT, NOT_NOW])
            else:
                proposal.purpose, proposal.spec = proposed.purpose, proposed.spec()
                card = AskArgs(text=proposed.card(), choices=[BUILD_IT, NOT_NOW])
            try:
                await self.proposals.create(proposal)
                asked = card
            except Exception as e:  # no card without its proposal stored, but Hansen still gets a reply
                log.exception("could not store the proposal for %s", proposed.name)
                reply_text = (
                    f"I drafted {'a change to ' if isinstance(proposed, ChangeArgs) else 'a module for this '}"
                    f"({proposed.name}) but couldn't save it ({type(e).__name__}), "
                )
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
    built = {
        p.name for p in offered if p.status == ProposalStatus.DONE and (p.channel, p.thread) == (channel, thread_id)
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


def _already(p: Proposal) -> str:
    """A tap on a card that was decided already: a second tap, or an old card."""
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
