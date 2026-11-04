"""Main on the bus.

    sense.chat      {id, channel, thread, text}            -> recall, plan, reply on out.say (or out.ask)
    sense.feedback  {ref, answer} | {ref, vote}            -> an answer continues the thread; a vote is traced
    brain.observe                                          -> v0: logged only (the gate comes with the snapshot)
    build.done / build.failed                              -> told in the thread whose proposal started it

Every handled message ends in one trace.plan with the pack, the tool calls, the model usage and the
reply, linked by `cause` to the message that started it.

Growing a module: `propose_module` ends the turn like `ask`; Main stores the proposal (proposals.py), then
sends its card with Build it / Not now. A tap on Build it is handled here, not by the model: it calls
rpc.build.start under the thread's lock, so a double tap or an old card finds the proposal decided.

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
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mycelium_sdk import (
    Bus,
    ChatMessage,
    CompletionReply,
    CompletionRequest,
    Envelope,
    Message,
    NoAnswer,
    Refused,
    Role,
    TextBlock,
    ToolUse,
    ask,
    kv_key,
    now_iso,
)
from mycelium_sdk.build import BuildRef, BuildRequest, StartReply

from .prompt import planner_prompt
from .proposals import Proposal, ProposalStatus, ProposalStore
from .schemas import (
    Ask,
    AskOutput,
    BuildOutcome,
    FeedbackTrace,
    LlmCall,
    ModuleInfo,
    PackSummary,
    PlanTrace,
    Say,
    SayOutput,
)
from .thread import ThreadStore, Turn, TurnCall
from .tools import AskArgs, ProposeArgs, RecallPayload, ToolContext, ToolOutcome, ToolRegistry, default_tools

log = logging.getLogger("mycelium.main")

MODEL_DOWN_REPLY = "I can't reach my model right now, so I can't answer this yet. I kept your message."
BUILD_IT = "Build it"
NOT_NOW = "Not now"
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
    r"|已記住|已记住|記下了|记下了|記住了|记住了|已記錄|已记录|已儲存|已保存|存好了|幫你記|帮你记",
    re.IGNORECASE | re.MULTILINE,
)  # not "nothing was saved", "I can remember it for you", or a module's own "logged 12 sessions"
RECHECK = (
    "(A note from Main's code, not from Hansen.) Your reply says something was saved, but no `remember` went "
    "through in this turn. If something from his message belongs in memory, call `remember` now. If a module that "
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
        if ref and answer in (BUILD_IT, NOT_NOW) and (proposal := await self.proposals.by_card(ref)):
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
            reply = f"OK, I won't build {p.name}. Ask me again whenever you want it."
        else:
            reply, offer_again = await self._start_build(p, data)
        await self.proposals.save(p)
        await self._tell(p, reply, data, answer=answer, offer_again=offer_again)

    async def _start_build(self, p: Proposal, data: dict[str, Any]) -> tuple[str, bool]:
        """What to say, and whether to send a fresh card: the apps take the buttons off a card once it is answered,
        so a start that did not happen needs a new one to try again."""
        call = BuildRequest(
            name=p.name,
            spec=p.spec,
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
                "otherwise choose Build it again."
            ), True
        except Refused as e:  # busy, coder not ready, name taken, or already started by a tap that timed out
            if await self._adopt(p):
                return _building(p), False
            p.note = str(e)
            return f"The builder won't start {p.name}: {p.short_note()}", True
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

    async def on_build(self, msg: Message) -> None:
        """build.done / build.failed of a build a proposal started; other builds (mctl) are not Main's."""
        outcome = BuildOutcome.from_event(msg.subject, msg.data)
        channel, thread = msg.data.get("channel"), msg.data.get("thread")
        if not outcome.build_id or not channel or not thread:
            return
        async with self._lock(str(channel), str(thread)):  # the tap that started it holds this lock until saved
            p = await self.proposals.by_build(outcome.build_id)
            if p is None:  # its start went unanswered at the tap: the latest proposal of that name, in this thread
                latest = await self.proposals.by_name(str(msg.data.get("name") or ""))
                if (
                    latest
                    and latest.status == ProposalStatus.PROPOSED
                    and (latest.channel, latest.thread)
                    == (
                        channel,
                        thread,
                    )
                ):
                    latest.status, latest.build_id = ProposalStatus.BUILDING, outcome.build_id
                    p = latest
            if p is not None and p.status == ProposalStatus.BUILDING:
                await self._finish(p, outcome, msg.data)

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
                record = await self.bus.request("rpc.build.get", BuildRef(build_id=p.build_id or "?"), timeout=5.0)
            except Exception:
                return False
            if record.get("ok"):
                outcome = BuildOutcome.from_record(record)
            elif "no build" in str(record.get("error")):  # it answers, but lost the record: it will never report
                outcome = BuildOutcome(
                    build_id=p.build_id or "", done=False, stage="unknown", error="the builder has no record of it"
                )
            else:
                return False
            if outcome is None:  # still queued or building: its build.done/failed will come
                continue
            async with self._lock(p.channel, p.thread):
                fresh = await self.proposals.get(p.id)
                if fresh is not None and fresh.status == ProposalStatus.BUILDING:
                    await self._finish(fresh, outcome, {})
        return True

    async def _finish(self, p: Proposal, outcome: BuildOutcome, data: dict[str, Any]) -> None:
        if outcome.done:
            p.status = ProposalStatus.DONE
            version = f" (version {outcome.version})" if outcome.version else ""
            reply = f"{p.name} is built and running{version}. Ask me about it any time."
        else:
            p.status = ProposalStatus.FAILED
            p.note = f"{outcome.stage or 'unknown stage'}: {outcome.error or 'no error given'}"
            reply = f"Building {p.name} failed at {outcome.stage or 'an unknown stage'}: {(outcome.error or '')[:ERROR_SHOWN]}"
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
            choices = [BUILD_IT, NOT_NOW]
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
        prompt = planner_prompt(self.today(), self.tz, channel, text, pack, modules, recall_error, offered)
        messages = [*thread.messages(self.zone), ChatMessage(role=Role.USER, content=prompt.user)]

        tool_log: list[ToolOutcome] = []
        llm_calls: list[LlmCall] = []
        reply_text = ""
        asked: AskArgs | None = None
        proposed: ProposeArgs | None = None
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
                outcome = await self.tools.call(c.name, c.input, self.ctx)
                if asked is None and proposed is None:  # the first valid `ask` or proposal ends the turn
                    if isinstance(outcome.args, AskArgs):
                        asked = outcome.args
                    elif isinstance(outcome.args, ProposeArgs) and outcome.ok:  # not when the name is taken
                        proposed = outcome.args
                tool_log.append(outcome)
                results.append(outcome.tool_result(c.id, MAX_TOOL_RESULT_CHARS))
            messages.append(ChatMessage(role=Role.USER, content=results))
            if asked or proposed:
                reply_text = r.text.strip()  # reasoning models lead with blank lines
                break
        else:
            error = f"planner did not finish in {self.max_rounds} rounds"

        out = Envelope.child_of(data, "main")
        output: SayOutput | AskOutput
        if proposed and not error:  # stored before its card goes out: the tap finds it by the card's id
            proposal = Proposal(
                id=out.id,
                name=proposed.name,
                purpose=proposed.purpose,
                spec=proposed.spec(),
                channel=channel,
                thread=thread_id,
                cause=cause,
            )
            try:
                await self.proposals.create(proposal)
                asked = AskArgs(text=proposed.card(), choices=[BUILD_IT, NOT_NOW])
            except Exception as e:  # no card without its proposal stored, but Hansen still gets a reply
                log.exception("could not store the proposal for %s", proposed.name)
                reply_text = (
                    f"I drafted a module for this ({proposed.name}) but couldn't save it ({type(e).__name__}), "
                )
                reply_text += "so I can't offer it right now. Ask me again in a moment."
                proposed = None
        if asked and not error:
            question = "\n\n".join(s for s in (reply_text, asked.text) if s)
            await self.bus.publish(
                "out.ask",
                out.into(Ask, channel=channel, thread=thread_id, text=question, choices=asked.choices, ref=out.id),
            )
            saved = f"{question}\n[choices: {' / '.join(asked.choices)}]"
            output = AskOutput(ask=asked)
        else:
            if error or not reply_text:
                reply_text = MODEL_DOWN_REPLY if error else "(no reply)"
            await self.bus.publish("out.say", out.into(Say, channel=channel, thread=thread_id, text=reply_text))
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

    async def _modules(self) -> list[ModuleInfo]:
        try:
            reply = await self.bus.request("rpc.sys.list", {}, timeout=2.0)
        except Exception:
            return []
        out: list[ModuleInfo] = []
        for row in reply.get("modules") or []:
            if row.get("status") not in (None, "running"):
                continue
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
                )
            )
        return out


def _unbacked_claim(text: str, tools: list[ToolOutcome], modules: list[ModuleInfo]) -> bool:
    """The reply says something was saved, no `remember` went through, and it names no module that hears the chat
    (one that logged the message itself, as the policy asks it to say)."""
    if not CLAIM.search(text) or any(o.name == "remember" and o.ok for o in tools):
        return False
    lowered = text.lower()
    return not any(m.name.lower() in lowered for m in modules if "sense.chat" in m.listens)


def _kept(tools: list[ToolOutcome]) -> list[TurnCall]:
    """The calls a turn keeps in its thread: those Main accepted (a rejected one taught nothing worth repeating)."""
    return [TurnCall.of(o.name, o.input, o.result) for o in tools if o.args is not None]


def _already(p: Proposal) -> str:
    """A tap on a card that was decided already: a second tap, or an old card."""
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
    return f"Building {p.name}{ahead}. I'll tell you here when it's running."
