"""Main v0 over an in-memory bus: recall -> plan (with tools) -> reply -> trace, and the thread in KV."""

import asyncio
import json
import time
from datetime import date

import pytest
from pydantic import ValidationError

from main.prompt import render_pack, system_prompt
from main.schemas import ModuleInfo, PlanTrace
from main.service import MODEL_DOWN_REPLY, MainService
from main.thread import ThreadStore
from main.tools import ToolContext, default_tools
from mycelium_sdk import Envelope, InMemoryBus, InMemoryKV, Message

TODAY = date(2026, 10, 23)
TOOL_SPECS = [s.model_dump() for s in default_tools().specs()]

PACK = {
    "ok": True,
    "query": "what did 小美 recommend?",
    "items": [
        {
            "note": "people/mei.md",
            "why": "小美 is an alias of mei",
            "excerpt": '2026-09-02 recommended the book "Project Hail Mary"',
        },
        {
            "note": "places/ramen-place-xinyi.md",
            "why": "linked from people/mei.md",
            "excerpt": "Ramen shop near Xinyi Anhe.",
        },
    ],
    "used": {"dates": [], "names": ["mei"], "embedding": False},
    "budget": {"notes_opened": 2, "max": 8},
}


class World:
    """Fake memory, gateway and supervisor on the bus. The gateway answers from a script."""

    def __init__(self, bus: InMemoryBus, llm_script: list[dict]):
        self.bus = bus
        self.llm_script = list(llm_script)
        self.llm_requests: list[dict] = []
        self.llm_delay = 0.0  # seconds the fake gateway takes per round
        self.remembered: list[dict] = []
        self.module_calls: list[tuple[str, dict]] = []
        self.recall_reply: dict | None = PACK
        self.svc: MainService
        self.modules = [
            {
                "name": "expenses",
                "status": "running",
                "manifest": {"purpose": "Tracks spending.", "requests": ["summary"]},
            }
        ]

    async def start(self):
        await self.bus.subscribe("rpc.llm.complete", self._llm)
        await self.bus.subscribe("rpc.memory.recall", self._recall)
        await self.bus.subscribe("rpc.memory.remember", self._remember)
        await self.bus.subscribe("rpc.sys.list", self._list)
        await self.bus.subscribe("rpc.mod.expenses.summary", self._expenses)

    async def send(self, subject: str, data: dict):
        """Publish like a channel would, then wait for Main's task to finish (handlers run as tasks)."""
        await self.bus.publish(subject, data)
        await self.svc.drain()

    async def _llm(self, msg: Message):
        self.llm_requests.append(msg.data)
        if self.llm_delay:
            await asyncio.sleep(self.llm_delay)
        last = msg.data["messages"][-1]["content"]
        reply = (
            self.llm_script.pop(0) if self.llm_script else say(f"re:{last}")  # no script: echo the last user message
        )
        await msg.respond(reply)

    async def _recall(self, msg: Message):
        if self.recall_reply is None:
            await msg.respond({"ok": False, "error": "index down"})
        else:
            await msg.respond(self.recall_reply)

    async def _remember(self, msg: Message):
        self.remembered.append(msg.data)
        await msg.respond({"ok": True, "path": f"people/{msg.data['note']}.md", "created": False})

    async def _list(self, msg: Message):
        await msg.respond({"ok": True, "modules": self.modules})

    async def _expenses(self, msg: Message):
        self.module_calls.append((msg.subject, msg.data))
        await msg.respond({"ok": True, "total_twd": 4210, "month": "2026-10"})


def say(text, cost=0.001):
    return {
        "ok": True,
        "text": text,
        "tool_calls": [],
        "stop_reason": "end_turn",
        "model": "claude-sonnet-5-5",
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "cost_usd": cost,
    }


def call(name, input, id="t1", text=""):
    return {
        "ok": True,
        "text": text,
        "tool_calls": [{"id": id, "name": name, "input": input}],
        "stop_reason": "tool_use",
        "model": "claude-sonnet-5-5",
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "cost_usd": 0.001,
    }


def chat(text, channel="telegram", thread="123"):
    return Message(subject="sense.chat", data=Envelope(source=channel).stamp(channel=channel, thread=thread, text=text))


@pytest.fixture
async def world():
    bus = InMemoryBus()
    w = World(bus, [])
    await w.start()
    w.svc = MainService(bus, ThreadStore(InMemoryKV(), max_turns=6), today=lambda: TODAY, tz="Asia/Taipei")
    await w.svc.start()
    return w


# ---- prompt ------------------------------------------------------------------------------------


def test_system_prompt_has_date_pack_and_modules():
    s = system_prompt(
        TODAY,
        "Asia/Taipei",
        "telegram",
        PACK,
        [ModuleInfo(name="expenses", purpose="Tracks spending.", requests=["expenses.summary"])],
    )
    assert "Friday 2026-10-23 (Asia/Taipei)" in s and "over telegram" in s
    assert "- people/mei.md (小美 is an alias of mei): 2026-09-02 recommended" in s
    assert "- expenses: Tracks spending. Requests: expenses.summary" in s


def test_render_pack_states_when_memory_is_empty_or_down():
    assert render_pack({"items": []}).startswith("(nothing matched")
    assert render_pack(None, "TimeoutError") == "(memory unavailable: TimeoutError)"


# ---- tools as pydantic models ------------------------------------------------------------------------


def test_tool_specs_are_generated_from_the_argument_models():
    specs = {s.name: s for s in default_tools().specs()}
    assert set(specs) == {"remember", "recall", "ask_module", "ask"}
    remember = specs["remember"].input_schema
    assert remember["type"] == "object" and remember["required"] == ["note"]
    assert remember["properties"]["type"]["enum"][:3] == ["self", "person", "place"]
    assert remember["properties"]["day"] == {
        "type": "string",
        "format": "date",
        "description": "YYYY-MM-DD the fact is about; default today",
    }
    assert "title" not in json.dumps(remember) and "anyOf" not in json.dumps(remember)  # trimmed for the model
    choices = specs["ask"].input_schema["properties"]["choices"]
    assert choices["minItems"] == 2 and choices["maxItems"] == 6
    assert specs["ask_module"].input_schema["properties"]["module"]["pattern"].startswith("^[a-z]")


async def test_registry_never_raises_and_dumps_as_the_trace_entry():
    reg = default_tools()
    ctx = ToolContext(bus=InMemoryBus())  # nobody answers on this bus
    unknown = await reg.call("fly", {"to": "tainan"}, ctx)
    assert not unknown.ok and unknown.args is None and "unknown tool 'fly'" in unknown.result["error"]
    bad = await reg.call("remember", {"note": "mei", "day": "2026-10-23"}, ctx)
    assert not bad.ok and "day only makes sense together with a fact" in bad.result["error"]
    down = await reg.call("recall", {"query": "mei"}, ctx)
    assert not down.ok and down.result["error"].startswith("TimeoutError") and down.args is not None
    assert down.model_dump() == {"name": "recall", "input": {"query": "mei"}, "result": down.result}
    block = down.tool_result("t1", limit=20)
    assert block["type"] == "tool_result" and block["tool_use_id"] == "t1" and len(block["content"]) == 20


# ---- one message, end to end -----------------------------------------------------------------------


async def test_chat_recalls_plans_replies_and_traces(world):
    world.llm_script = [say("She recommended Project Hail Mary.")]
    incoming = chat("what did 小美 recommend?")
    await world.send(incoming.subject, incoming.data)

    req = world.llm_requests[0]
    assert req["slot"] == "planner" and req["cause"] == incoming.data["id"] and req["tools"] == TOOL_SPECS
    assert "people/mei.md (小美 is an alias of mei)" in req["system"]
    assert req["messages"] == [{"role": "user", "content": "what did 小美 recommend?"}]

    says = world.bus.events("out.say")
    assert len(says) == 1
    out = says[0][1]
    assert out["text"] == "She recommended Project Hail Mary."
    assert out["channel"] == "telegram" and out["thread"] == "123"
    assert out["cause"] == incoming.data["id"] and out["source"] == "main" and out["hops"] == 1

    trace = world.bus.events("trace.plan")[0][1]
    assert trace["cause"] == incoming.data["id"] and trace["input"] == "what did 小美 recommend?"
    assert trace["pack"]["items"] == [
        {"note": "people/mei.md", "why": "小美 is an alias of mei"},
        {"note": "places/ramen-place-xinyi.md", "why": "linked from people/mei.md"},
    ]
    assert trace["output"] == {"say": "She recommended Project Hail Mary."} and trace["error"] is None
    assert trace["rounds"] == 1 and trace["cost_usd"] == 0.001 and trace["modules"] == ["expenses"]

    thread = await world.svc.store.load("telegram", "123")
    assert [(t.role, t.text) for t in thread.turns] == [
        ("user", "what did 小美 recommend?"),
        ("assistant", "She recommended Project Hail Mary."),
    ]
    assert thread.turns[0].id == incoming.data["id"] and thread.turns[1].id == out["id"]


async def test_thread_history_is_sent_back_per_channel_and_thread(world):
    world.llm_script = [say("A"), say("B"), say("C")]
    await world.send("sense.chat", chat("one").data)
    await world.send("sense.chat", chat("two").data)
    await world.send("sense.chat", chat("other", channel="cli", thread="x").data)
    assert world.llm_requests[1]["messages"] == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "A"},
        {"role": "user", "content": "two"},
    ]
    assert world.llm_requests[2]["messages"] == [{"role": "user", "content": "other"}]


async def test_thread_keeps_only_the_last_turns(world):
    world.llm_script = [say(str(i)) for i in range(5)]
    for i in range(5):
        await world.send("sense.chat", chat(f"m{i}").data)
    thread = await world.svc.store.load("telegram", "123")
    assert len(thread.turns) == 6  # max_turns
    assert thread.turns[0].text == "m2"


# ---- tools ---------------------------------------------------------------------------------------


async def test_remember_tool_writes_memory_then_answers(world):
    world.llm_script = [
        call(
            "remember",
            {
                "note": "mei",
                "type": "person",
                "aliases": ["小美"],
                "fact": "is moving to Tainan in December",
                "day": "2026-10-23",
            },
            text="Noted.",
        ),
        say("Got it, Mei is moving to Tainan in December."),
    ]
    await world.send("sense.chat", chat("remember that 小美 is moving to Tainan in December").data)

    assert world.remembered == [
        {
            "note": "mei",
            "source": "hansen",
            "type": "person",
            "aliases": ["小美"],
            "fact": {"text": "is moving to Tainan in December", "day": "2026-10-23"},
        }
    ]
    second = world.llm_requests[1]["messages"]
    assert second[1]["role"] == "assistant"
    assert second[1]["content"][0] == {"type": "text", "text": "Noted."}
    assert second[1]["content"][1]["type"] == "tool_use" and second[1]["content"][1]["name"] == "remember"
    assert second[2]["role"] == "user" and second[2]["content"][0]["type"] == "tool_result"
    assert json.loads(second[2]["content"][0]["content"])["path"] == "people/mei.md"

    assert world.bus.events("out.say")[0][1]["text"] == "Got it, Mei is moving to Tainan in December."
    trace = world.bus.events("trace.plan")[0][1]
    assert trace["rounds"] == 2 and trace["cost_usd"] == 0.002
    assert trace["tools"][0]["name"] == "remember" and trace["tools"][0]["result"]["ok"]


async def test_ask_module_tool_calls_the_module(world):
    world.llm_script = [
        call("ask_module", {"module": "expenses", "action": "summary", "args": {"month": "2026-10"}}),
        say("4,210 TWD this month."),
    ]
    await world.send("sense.chat", chat("how much did I spend this month?").data)
    assert world.module_calls == [("rpc.mod.expenses.summary", {"month": "2026-10"})]
    result = json.loads(world.llm_requests[1]["messages"][2]["content"][0]["content"])
    assert result["total_twd"] == 4210


async def test_bad_module_name_and_unknown_tool_return_errors_to_the_model(world):
    world.llm_script = [
        call("ask_module", {"module": "../x", "action": "summary"}),
        call("fly", {}, id="t2"),
        say("ok"),
    ]
    await world.send("sense.chat", chat("x").data)
    first = json.loads(world.llm_requests[1]["messages"][2]["content"][0]["content"])
    assert not first["ok"] and first["error"].startswith("module: String should match pattern")
    second = json.loads(world.llm_requests[2]["messages"][4]["content"][0]["content"])
    assert not second["ok"] and "unknown tool" in second["error"]
    assert world.bus.events("out.say")[0][1]["text"] == "ok"
    assert world.module_calls == []  # the bad name never reached the bus


async def test_bad_tool_input_is_rejected_before_the_bus_and_a_bad_ask_does_not_end_the_turn(world):
    world.llm_script = [
        call("ask", {"text": "which?", "choices": ["only one"]}),
        call("remember", {"note": "mei", "fact": "moved", "day": "yesterday"}, id="t2"),
        say("ok"),
    ]
    await world.send("sense.chat", chat("x").data)
    first = json.loads(world.llm_requests[1]["messages"][2]["content"][0]["content"])
    assert not first["ok"] and first["error"].startswith("choices: List should have at least 2 items")
    second = json.loads(world.llm_requests[2]["messages"][4]["content"][0]["content"])
    assert not second["ok"] and second["error"].startswith("day: ")
    assert world.remembered == [] and not world.bus.events("out.ask")
    assert world.bus.events("out.say")[0][1]["text"] == "ok"
    trace = world.bus.events("trace.plan")[0][1]
    assert [t["name"] for t in trace["tools"]] == ["ask", "remember"] and not trace["tools"][0]["result"]["ok"]


async def test_ask_tool_publishes_out_ask_and_the_answer_continues_the_thread(world):
    world.llm_script = [
        call("ask", {"text": "Book the 7pm or the 9pm?", "choices": ["7pm", "9pm"]}, text="Two options."),
        say("Booked 9pm."),
    ]
    incoming = chat("book the ramen place tonight")
    await world.send("sense.chat", incoming.data)

    asks = world.bus.events("out.ask")
    assert len(asks) == 1 and not world.bus.events("out.say")
    ask = asks[0][1]
    assert ask["text"] == "Two options.\n\nBook the 7pm or the 9pm?" and ask["choices"] == ["7pm", "9pm"]
    assert (
        ask["channel"] == "telegram"
        and ask["thread"] == "123"
        and ask["ref"] == ask["id"]
        and ask["cause"] == incoming.data["id"]
    )
    assert world.bus.events("trace.plan")[0][1]["output"] == {
        "ask": {"text": "Book the 7pm or the 9pm?", "choices": ["7pm", "9pm"]}
    }

    await world.send(
        "sense.feedback",
        Envelope(source="telegram").stamp(channel="telegram", thread="123", ref=ask["id"], answer="9pm"),
    )
    assert world.llm_requests[1]["messages"] == [
        {"role": "user", "content": "book the ramen place tonight"},
        {"role": "assistant", "content": "Two options.\n\nBook the 7pm or the 9pm?\n[choices: 7pm / 9pm]"},
        {"role": "user", "content": "9pm"},
    ]
    assert world.bus.events("out.say")[0][1]["text"] == "Booked 9pm."
    fb = world.bus.events("trace.feedback")[0][1]
    assert fb["ref"] == ask["id"] and fb["answer"] == "9pm"


async def test_vote_feedback_is_traced_only(world):
    await world.send("sense.feedback", Envelope(source="telegram").stamp(ref="abc", vote=-1))
    assert world.bus.events("trace.feedback")[0][1]["vote"] == -1
    assert not world.llm_requests


# ---- degraded paths ------------------------------------------------------------------------------


async def test_memory_down_still_answers_and_says_so_in_the_prompt(world):
    world.recall_reply = None
    world.llm_script = [say("hi")]
    await world.send("sense.chat", chat("hello").data)
    assert "(memory unavailable: index down)" in world.llm_requests[0]["system"]
    assert world.bus.events("out.say")[0][1]["text"] == "hi"
    assert world.bus.events("trace.plan")[0][1]["recall_error"] == "index down"


async def test_gateway_failure_gives_a_degraded_reply_and_keeps_the_turn(world):
    world.llm_script = [{"ok": False, "error": "budget exceeded: $30.00 of $30.00 this month"}]
    await world.send("sense.chat", chat("hello").data)
    assert world.bus.events("out.say")[0][1]["text"] == MODEL_DOWN_REPLY
    trace = world.bus.events("trace.plan")[0][1]
    assert trace["error"].startswith("budget exceeded") and trace["rounds"] == 0
    thread = await world.svc.store.load("telegram", "123")
    assert thread.turns[0].text == "hello"  # the message is kept even when the model is down


async def test_tool_loop_stops_after_max_rounds(world):
    world.svc.max_rounds = 2
    world.llm_script = [call("recall", {"query": "a"}), call("recall", {"query": "b"}, id="t2"), say("never reached")]
    await world.send("sense.chat", chat("loop").data)
    trace = world.bus.events("trace.plan")[0][1]
    assert trace["error"] == "planner did not finish in 2 rounds" and trace["rounds"] == 2
    assert world.bus.events("out.say")[0][1]["text"] == MODEL_DOWN_REPLY


async def test_empty_text_is_ignored(world):
    await world.send("sense.chat", chat("   ").data)
    assert not world.llm_requests and not world.bus.events("out.say")


# ---- contracts and concurrency -------------------------------------------------------------------------


async def test_planner_request_carries_cause_hops_and_timeout_and_trace_plan_is_typed(world):
    world.llm_script = [say("hi")]
    incoming = Message(
        subject="sense.chat",
        data=Envelope(source="telegram", hops=2).stamp(channel="telegram", thread="123", text="hello"),
    )
    await world.send(incoming.subject, incoming.data)
    req = world.llm_requests[0]
    assert req["cause"] == incoming.data["id"] and req["hops"] == 2 and req["timeout"] == world.svc.llm_timeout
    trace = world.bus.events("trace.plan")[0][1]
    parsed = PlanTrace.model_validate(trace)  # what went on the bus is exactly the model
    assert parsed.hops == 3 and parsed.reply_id == world.bus.events("out.say")[0][1]["id"]
    assert parsed.output.say == "hi" and parsed.llm_calls[0].usage.input_tokens == 100


async def test_turns_on_one_thread_are_serialized_and_threads_run_in_parallel(world):
    world.llm_script = []  # the fake gateway echoes, so replies are tied to the message and not to arrival order
    world.llm_delay = 0.05
    t0 = time.monotonic()
    await world.bus.publish("sense.chat", chat("one").data)  # same thread, back to back, no draining between
    await world.bus.publish("sense.chat", chat("two").data)
    await world.bus.publish("sense.chat", chat("other", channel="cli", thread="x").data)
    await world.svc.drain()
    assert time.monotonic() - t0 < 0.14  # the cli turn ran beside the telegram ones, not after them
    thread = await world.svc.store.load("telegram", "123")
    assert [t.text for t in thread.turns] == ["one", "re:one", "two", "re:two"]  # nothing overwritten, in order
    second = next(r for r in world.llm_requests if r["messages"][-1]["content"] == "two")
    assert second["messages"][:2] == [{"role": "user", "content": "one"}, {"role": "assistant", "content": "re:one"}]
    assert [t.text for t in (await world.svc.store.load("cli", "x")).turns] == ["other", "re:other"]


def test_remember_args_accept_the_pack_path_and_split_a_leading_date():
    from datetime import date

    from main.tools import RememberArgs

    a = RememberArgs(note="people/mei.md", fact="2026-10-23 is moving to Tainan in December")
    assert a.note == "mei" and a.fact == "is moving to Tainan in December" and a.day == date(2026, 10, 23)
    b = RememberArgs(note=" Mei ", fact="likes ramen", day=date(2026, 10, 1))
    assert b.note == "mei" and b.day == date(2026, 10, 1)
    with pytest.raises(ValidationError, match="summary"):  # a day summary is not an entity
        RememberArgs(note="summaries/2026/10/14.md", fact="x")


def test_ask_module_args_accept_the_prefixed_request_name_the_prompt_shows():
    from main.tools import AskModuleArgs

    assert AskModuleArgs(module="hello", action="hello.stats").action == "stats"
    assert AskModuleArgs(module="hello", action="stats").action == "stats"
    with pytest.raises(ValidationError):
        AskModuleArgs(module="hello", action="other.stats")  # a different module's request is not a slip
