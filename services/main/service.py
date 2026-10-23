"""Main on the bus.

    sense.chat      {id, channel, thread, text}            -> recall, plan, reply on out.say (or out.ask)
    sense.feedback  {ref, answer} | {ref, vote}            -> an answer continues the thread; a vote is traced
    brain.observe                                          -> v0: logged only (the gate comes with the snapshot)

Every handled message ends in one trace.plan with the pack, the tool calls, the model usage and the
reply, linked by `cause` to the message that started it.

Each message is handled in its own task, so one slow turn never holds up the others; turns on the
same (channel, thread) take a lock, so a typed message and a button tap cannot interleave.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from datetime import date
from typing import Any

from mycelium_sdk import Bus, Envelope, Message, kv_key

from .prompt import system_prompt
from .schemas import (
    Ask,
    AskOutput,
    FeedbackTrace,
    LlmCall,
    ModuleInfo,
    PackSummary,
    PlannerRequest,
    PlanTrace,
    Say,
    SayOutput,
)
from .thread import ThreadStore, Turn
from .tools import AskArgs, RecallPayload, ToolContext, ToolOutcome, ToolRegistry, default_tools

log = logging.getLogger("mycelium.main")

MODEL_DOWN_REPLY = "I can't reach my model right now, so I can't answer this yet. I kept your message."
MAX_TOOL_RESULT_CHARS = 4000
BUS_MARGIN_S = 5.0  # the gateway enforces the timeout; Main waits a little longer for its clean error


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
        tools: ToolRegistry | None = None,
    ) -> None:
        self.bus = bus
        self.store = store
        self.today = today
        self.tz = tz
        self.max_rounds = max_rounds
        self.recall_budget = recall_budget
        self.llm_timeout = llm_timeout
        self.tools = tools or default_tools()
        self.ctx = ToolContext(bus=bus, recall_budget=recall_budget)
        self._tool_specs = [s.model_dump() for s in self.tools.specs()]
        self._tasks: set[asyncio.Task] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        await self.bus.connect()
        await self.bus.subscribe("sense.chat", self._dispatch(self.on_chat), queue="main")
        await self.bus.subscribe("sense.feedback", self._dispatch(self.on_feedback), queue="main")
        await self.bus.subscribe("brain.observe", self._dispatch(self.on_observe), queue="main")

    # ---- dispatch ------------------------------------------------------------------------

    def _dispatch(self, fn: Callable[[Message], Coroutine[Any, Any, None]]):
        async def handler(msg: Message) -> None:
            task = asyncio.create_task(self._run(fn, msg))  # return at once: NATS delivers one callback at a time
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        return handler

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
        if answer:
            await self.on_chat(Message(subject="sense.chat", data={**data, "text": answer}))

    async def on_observe(self, msg: Message) -> None:
        log.debug("observe (v0: log only): %s", msg.data.get("summary"))

    # ---- one turn ------------------------------------------------------------------------

    async def _turn(self, data: dict[str, Any], text: str, channel: str, thread_id: str) -> None:
        cause = data.get("id")
        t0 = time.monotonic()

        thread = await self.store.load(channel, thread_id)
        (pack, recall_error), modules = await asyncio.gather(self._recall(text), self._modules())
        system = system_prompt(self.today(), self.tz, channel, pack, modules, recall_error)
        messages: list[dict[str, Any]] = [*thread.messages(), {"role": "user", "content": text}]

        tool_log: list[ToolOutcome] = []
        llm_calls: list[LlmCall] = []
        reply_text = ""
        asked: AskArgs | None = None
        error: str | None = None

        for _round in range(self.max_rounds):
            request = PlannerRequest(
                system=system,
                messages=messages,
                tools=self._tool_specs,
                cause=cause,
                hops=int(data.get("hops") or 0),
                timeout=self.llm_timeout,
            )
            try:
                r = await self.bus.request("rpc.llm.complete", request, timeout=self.llm_timeout + BUS_MARGIN_S)
            except Exception as e:
                r = {"ok": False, "error": f"gateway unreachable: {type(e).__name__}: {e}"}
            if not r.get("ok"):
                error = str(r.get("error") or "gateway error")
                break
            llm_calls.append(LlmCall.model_validate(r))
            calls = r.get("tool_calls") or []
            if not calls:
                reply_text = str(r.get("text") or "")
                break

            content: list[dict[str, Any]] = []
            if r.get("text"):
                content.append({"type": "text", "text": r["text"]})
            content += [
                {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c.get("input") or {}} for c in calls
            ]
            messages.append({"role": "assistant", "content": content})

            results: list[dict[str, Any]] = []
            for c in calls:
                outcome = await self.tools.call(c["name"], c.get("input"), self.ctx)
                if isinstance(outcome.args, AskArgs):  # a valid `ask` ends the turn
                    asked = outcome.args
                tool_log.append(outcome)
                results.append(outcome.tool_result(c["id"], MAX_TOOL_RESULT_CHARS))
            messages.append({"role": "user", "content": results})
            if asked:
                reply_text = str(r.get("text") or "")
                break
        else:
            error = f"planner did not finish in {self.max_rounds} rounds"

        out = Envelope.child_of(data, "main")
        output: SayOutput | AskOutput
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
            Turn(role="user", text=text, ts=str(data.get("ts") or out.ts), id=cause),
            Turn(role="assistant", text=saved, ts=out.ts, id=out.id),
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
                )
            )
        return out
