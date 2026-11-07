"""Main grows a module: propose_module -> the proposal stored -> its card -> a tap -> rpc.build.start -> the result
in the thread that asked. The tap is handled in code: the model is never asked whether to build."""

import pytest
from pydantic import ValidationError

from main.prompt import render_modules
from main.proposals import Proposal, ProposalStatus, ProposalStore
from main.schemas import ModuleInfo, PlanTrace
from main.service import BUILD_IT, NOT_NOW, MainService
from main.thread import ThreadStore
from main.tools import ProposeArgs
from mycelium_sdk import Envelope, InMemoryBus, InMemoryKV, Message
from tests.unit.test_main import TODAY, World, call, chat, say

EXPENSES = {
    "name": "expenses",
    "purpose": "Tracks spending from chat and answers totals.",
    "need": "Hansen mentions spending in chat and later asks how much he spent.",
    "behaviour": [
        "listens to sense.chat and stores messages that look like an expense: an amount and a description",
        "ignores messages without an amount, and times like 'at 7'",
    ],
    "answers": ["summary: totals for a date range and the top descriptions"],
    "example": "dinner 350",
}


class Builder:
    """rpc.build.start / rpc.build.get / rpc.build.list as the builder answers them."""

    def __init__(self, bus: InMemoryBus):
        self.bus = bus
        self.started: list[dict] = []
        self.refuse: str | None = None
        self.down = False  # rpc.build.start gets no answer, and nothing is queued
        self.slow = False  # rpc.build.start gets no answer in time, but the build is queued
        self.records: dict[str, dict] = {}

    async def start(self):
        await self.bus.subscribe("rpc.build.start", self._start)
        await self.bus.subscribe("rpc.build.get", self._get)
        await self.bus.subscribe("rpc.build.list", self._list)

    async def _start(self, msg: Message):
        if self.down:
            return  # no reply: the caller times out
        if self.refuse:
            await msg.respond({"ok": False, "error": self.refuse})
            return
        self.started.append(msg.data)
        build_id = f"b{len(self.started)}"
        self.records[build_id] = {  # a BuildRecord, as rpc.build.get answers it
            "id": build_id,
            "name": msg.data["name"],
            "spec": msg.data.get("spec") or msg.data.get("change") or "",
            "coder": "fake",
            "mode": "change" if msg.data.get("change") else "new",
            "status": "queued",
            "channel": msg.data.get("channel"),
            "thread": msg.data.get("thread"),
        }
        if not self.slow:
            await msg.respond({"ok": True, "build_id": build_id, "position": 0})

    async def _get(self, msg: Message):
        record = self.records.get(msg.data["build_id"])
        await msg.respond(
            {"ok": True, **record} if record else {"ok": False, "error": f"no build {msg.data['build_id']!r}"}
        )

    async def _list(self, msg: Message):
        await msg.respond({"ok": True, "builds": list(self.records.values())})


@pytest.fixture
async def grow():
    bus = InMemoryBus()
    w = World(bus, [])
    w.modules = [  # no expenses yet: that is the module being grown
        {"name": "hello", "status": "running", "manifest": {"purpose": "Counts chat messages.", "requests": ["stats"]}}
    ]
    await w.start()
    w.builder = Builder(bus)
    await w.builder.start()
    w.kv = InMemoryKV()
    w.svc = MainService(bus, ThreadStore(w.kv, max_turns=10), today=lambda: TODAY, build_timeout=0.2)
    await w.svc.start()
    return w


def tap(ref: str, answer: str, channel="telegram", thread="123") -> dict:
    return Envelope(source=channel).stamp(channel=channel, thread=thread, ref=ref, answer=answer)


async def propose(w, args=EXPENSES, text="Here's a module for that.") -> dict:
    """One turn that ends in a proposal; returns the card (out.ask)."""
    w.llm_script = [call("propose_module", args, text=text)]
    await w.send("sense.chat", chat("I want to track my expenses").data)
    asks = w.bus.events("out.ask")
    assert asks, "the proposal should end in a card"
    return asks[-1][1]


# ---- the tool ----------------------------------------------------------------------------------------


def test_propose_args_render_the_spec_in_the_house_format():
    args = ProposeArgs.model_validate(EXPENSES)
    spec = args.spec()
    assert spec.startswith("# Spec: expenses\n\n**Observed need:** Hansen mentions spending")
    assert "**What to build:** Tracks spending from chat and answers totals." in spec
    assert "- ignores messages without an amount" in spec
    assert "- answers `summary`: totals for a date range" in spec
    assert 'An example message: "dinner 350"' in spec and spec.endswith("No network, no actuation.\n")


def test_propose_args_normalise_the_name_and_take_lines_as_one_block():
    args = ProposeArgs.model_validate({**EXPENSES, "name": "Water Log", "behaviour": "- logs water\n- sums a day\n"})
    assert args.name == "water-log" and args.behaviour == ["logs water", "sums a day"]


@pytest.mark.parametrize("name", ["main", "x", "9lives", "a" * 40])
def test_propose_args_refuse_a_reserved_or_malformed_name(name):
    with pytest.raises(ValidationError):
        ProposeArgs.model_validate({**EXPENSES, "name": name})


def test_the_card_shows_what_it_does_and_what_it_answers():
    card = ProposeArgs.model_validate(EXPENSES).card()
    assert card.startswith("A new module, expenses: Tracks spending")
    assert "Then I can ask it: summary." in card and "Nothing is built until you choose." in card


def test_the_module_list_says_what_a_module_listens_to():
    rendered = render_modules([ModuleInfo(name="expenses", purpose="Tracks spending.", listens=["sense.chat"])])
    assert rendered == "- expenses: Tracks spending. Listens to: sense.chat. Requests: no requests"


# ---- proposing ---------------------------------------------------------------------------------------


async def test_a_proposal_is_stored_before_its_card_goes_out(grow):
    stored_when_sent: list[Proposal | None] = []

    async def on_ask(msg: Message):
        stored_when_sent.append(await ProposalStore(grow.kv).get(msg.data["ref"]))

    await grow.bus.subscribe("out.ask", on_ask)
    card = await propose(grow)
    assert card["choices"] == [BUILD_IT, NOT_NOW]
    assert card["text"].startswith("Here's a module for that.\n\nA new module, expenses")
    p = stored_when_sent[0]
    assert p is not None and p.id == card["ref"] == card["id"] and p.status == ProposalStatus.PROPOSED
    assert p.spec.startswith("# Spec: expenses") and (p.channel, p.thread) == ("telegram", "123")
    assert grow.builder.started == []  # proposing builds nothing
    trace = PlanTrace.model_validate(grow.bus.events("trace.plan")[-1][1])
    assert trace.proposal == "expenses" and trace.output.ask.choices == [BUILD_IT, NOT_NOW]


async def test_a_name_in_use_goes_back_to_the_model_and_does_not_end_the_turn(grow):
    grow.modules.append({"name": "water", "status": "running", "manifest": {"purpose": "x", "requests": []}})
    grow.llm_script = [call("propose_module", {**EXPENSES, "name": "water"}), say("You already have water.")]
    await grow.send("sense.chat", chat("track my water").data)
    assert not grow.bus.events("out.ask")
    assert "a module with that name is deployed" in grow.llm_requests[1]["messages"][-1]["content"][0]["content"]
    assert grow.bus.events("out.say")[-1][1]["text"] == "You already have water."


async def test_names_in_use_cover_folders_and_running_builds(grow):
    from main.tools import ToolContext
    from main.tools.propose import names_in_use

    async def listed(msg: Message):
        modules = [{"name": "hello", "status": "running"}, {"name": "water", "status": "retired"}]
        await msg.respond({"ok": True, "modules": modules, "folders": ["hello", "stash"]})

    grow.bus._subs = [(s, h) for s, h in grow.bus._subs if s != "rpc.sys.list"]
    await grow.bus.subscribe("rpc.sys.list", listed)
    grow.builder.records["b9"] = {"id": "b9", "name": "tea", "status": "building"}
    grow.builder.records["b8"] = {"id": "b8", "name": "old", "status": "failed"}
    taken = await names_in_use(ToolContext(bus=grow.bus))
    assert taken == {
        "hello": "a module with that name is deployed",
        "stash": "a module with that name exists, though it is not running",
        "tea": "a module with that name is being built",
    }  # a retired module's name is free, as the builder sees it


async def test_the_prompt_lists_what_each_module_listens_to(grow):
    grow.modules[0]["manifest"]["subscribes"] = ["sense.chat"]
    await grow.send("sense.chat", chat("hi").data)
    system = grow.llm_requests[0]["system"]
    assert "- hello: Counts chat messages. Listens to: sense.chat. Requests: hello.stats" in system
    assert "Use `propose_module` when Hansen wants something ongoing" in system


# ---- the tap -----------------------------------------------------------------------------------------


async def test_build_it_starts_the_build_without_the_model(grow):
    card = await propose(grow)
    rounds_before = len(grow.llm_requests)
    await grow.send("sense.feedback", tap(card["ref"], BUILD_IT))
    assert len(grow.llm_requests) == rounds_before  # no planner round for a tap
    [start] = grow.builder.started
    assert start["name"] == "expenses" and start["spec"].startswith("# Spec: expenses")
    assert (start["channel"], start["thread"]) == ("telegram", "123") and start["cause"]
    p = await ProposalStore(grow.kv).get(card["ref"])
    assert p.status == ProposalStatus.BUILDING and p.build_id == "b1"
    assert grow.bus.events("out.say")[-1][1]["text"] == "Building expenses. I'll tell you here when it's running."
    turns = (await grow.svc.store.load("telegram", "123")).turns
    assert [t.text for t in turns[-2:]] == [BUILD_IT, "Building expenses. I'll tell you here when it's running."]


async def test_not_now_declines_and_builds_nothing(grow):
    card = await propose(grow)
    await grow.send("sense.feedback", tap(card["ref"], NOT_NOW))
    assert grow.builder.started == []
    assert (await ProposalStore(grow.kv).get(card["ref"])).status == ProposalStatus.DECLINED
    assert grow.bus.events("out.say")[-1][1]["text"].startswith("OK, I won't build expenses")


async def test_a_double_tap_starts_one_build(grow):
    card = await propose(grow)
    await grow.bus.publish("sense.feedback", tap(card["ref"], BUILD_IT))
    await grow.bus.publish("sense.feedback", tap(card["ref"], BUILD_IT))
    await grow.svc.drain()
    assert len(grow.builder.started) == 1
    assert (
        grow.bus.events("out.say")[-1][1]["text"]
        == "expenses is already being built. I'll tell you here when it's running."
    )


async def test_an_old_card_tapped_after_not_now_builds_nothing(grow):
    card = await propose(grow)
    await grow.send("sense.feedback", tap(card["ref"], NOT_NOW))
    await grow.send("sense.feedback", tap(card["ref"], BUILD_IT))
    assert grow.builder.started == []
    assert grow.bus.events("out.say")[-1][1]["text"].startswith("You chose not to build expenses")


async def test_builder_down_is_said_honestly_and_a_fresh_card_lets_him_try_again(grow):
    card = await propose(grow)
    grow.builder.down = True
    await grow.send("sense.feedback", tap(card["ref"], BUILD_IT))
    again = grow.bus.events("out.ask")[-1][1]  # the apps take the buttons off an answered card
    assert again["id"] != card["id"] and again["ref"] == again["id"] and again["choices"] == [BUILD_IT, NOT_NOW]
    assert again["text"].startswith("The builder didn't answer in time. If it starts expenses anyway")
    p = await ProposalStore(grow.kv).get(card["ref"])
    assert p.status == ProposalStatus.PROPOSED and p.note == "the builder did not answer"
    grow.builder.down = False
    await grow.send("sense.feedback", tap(again["ref"], BUILD_IT))  # the fresh card is the same proposal
    assert len(grow.builder.started) == 1
    assert (await ProposalStore(grow.kv).get(card["ref"])).status == ProposalStatus.BUILDING


async def test_a_start_that_timed_out_but_went_through_is_building(grow):
    card = await propose(grow)
    grow.builder.slow = True  # it queues the build, but answers after Main stopped waiting
    await grow.send("sense.feedback", tap(card["ref"], BUILD_IT))
    p = await ProposalStore(grow.kv).get(card["ref"])
    assert p.status == ProposalStatus.BUILDING and p.build_id == "b1"  # found in rpc.build.list, same thread
    assert grow.bus.events("out.say")[-1][1]["text"] == "Building expenses. I'll tell you here when it's running."
    await grow.send("build.done", build_event(version="0.1.0"))
    assert grow.bus.events("out.say")[-1][1]["text"].startswith("expenses is built and running")


async def test_a_build_whose_start_went_unanswered_is_still_told(grow):
    card = await propose(grow)
    grow.builder.down = True  # no answer, and rpc.build.list does not show it yet
    await grow.send("sense.feedback", tap(card["ref"], BUILD_IT))
    await grow.send("build.failed", build_event(build_id="b7", stage="tests", error="1 failed"))
    assert grow.bus.events("out.say")[-1][1]["text"] == "Building expenses failed at tests: 1 failed"
    p = await ProposalStore(grow.kv).get(card["ref"])
    assert p.status == ProposalStatus.FAILED and p.build_id == "b7"


async def test_a_refusal_is_told_with_a_fresh_card(grow):
    card = await propose(grow)
    grow.builder.refuse = "the builder is busy: 3 builds are waiting; try again later"
    await grow.send("sense.feedback", tap(card["ref"], BUILD_IT))
    again = grow.bus.events("out.ask")[-1][1]
    assert (
        again["text"] == "The builder won't start expenses: the builder is busy: 3 builds are waiting; try again later"
    )
    assert (await ProposalStore(grow.kv).get(card["ref"])).status == ProposalStatus.PROPOSED
    turns = (await grow.svc.store.load("telegram", "123")).turns
    assert turns[-1].text.endswith("[choices: Build it / Not now]")


async def test_a_refusal_for_a_build_this_thread_already_started_adopts_it(grow):
    card = await propose(grow)
    record = {"id": "b1", "name": "expenses", "status": "building", "channel": "telegram", "thread": "123"}
    grow.builder.records["b1"] = record
    grow.builder.refuse = "'expenses' is already being built (b1)"
    await grow.send("sense.feedback", tap(card["ref"], BUILD_IT))
    p = await ProposalStore(grow.kv).get(card["ref"])
    assert p.status == ProposalStatus.BUILDING and p.build_id == "b1"


async def test_a_proposal_that_cannot_be_stored_gets_a_reply_not_silence(grow):
    async def broken(*_a, **_k):
        raise OSError("kv down")

    grow.svc.proposals.create = broken
    await propose_without_card(grow)
    assert not grow.bus.events("out.ask")
    text = grow.bus.events("out.say")[-1][1]["text"]
    assert text.startswith("I drafted a module for this (expenses) but couldn't save it (OSError)")
    assert PlanTrace.model_validate(grow.bus.events("trace.plan")[-1][1]).proposal is None


async def propose_without_card(w, args=EXPENSES):
    w.llm_script = [call("propose_module", args)]
    await w.send("sense.chat", chat("I want to track my expenses").data)


async def test_an_answer_to_an_ordinary_ask_still_continues_the_thread(grow):
    grow.llm_script = [call("ask", {"text": "Which day?", "choices": ["Mon", "Tue"]})]
    await grow.send("sense.chat", chat("plan climbing").data)
    ask = grow.bus.events("out.ask")[-1][1]
    grow.llm_script = [say("Tuesday it is.")]
    await grow.send("sense.feedback", tap(ask["id"], "Tue"))
    assert grow.bus.events("out.say")[-1][1]["text"] == "Tuesday it is."


async def test_build_it_typed_without_a_card_is_just_a_message(grow):
    grow.llm_script = [say("Build what?")]
    await grow.send("sense.feedback", tap("not-a-proposal", BUILD_IT))
    assert grow.builder.started == [] and grow.bus.events("out.say")[-1][1]["text"] == "Build what?"


# ---- the result --------------------------------------------------------------------------------------


async def built(grow) -> str:
    card = await propose(grow)
    await grow.send("sense.feedback", tap(card["ref"], BUILD_IT))
    return card["ref"]


def build_event(build_id="b1", channel="telegram", thread="123", **extra) -> dict:
    return Envelope(source="builder").stamp(
        build_id=build_id,
        name="expenses",
        coder="mycelium",
        rounds=2,
        seconds=90.0,
        channel=channel,
        thread=thread,
        **extra,
    )


async def test_build_done_is_told_in_the_thread_that_asked(grow):
    ref = await built(grow)
    await grow.send("build.done", build_event(version="0.1.0"))
    say_ = grow.bus.events("out.say")[-1][1]
    assert (say_["channel"], say_["thread"]) == ("telegram", "123")
    assert say_["text"] == "expenses is built and running (version 0.1.0). Ask me about it any time."
    assert (await ProposalStore(grow.kv).get(ref)).status == ProposalStatus.DONE
    assert (await grow.svc.store.load("telegram", "123")).turns[-1].text == say_["text"]


async def test_build_failed_says_where_and_why(grow):
    ref = await built(grow)
    await grow.send("build.failed", build_event(stage="tests", error="2 tests failed after 6 rounds"))
    assert (
        grow.bus.events("out.say")[-1][1]["text"] == "Building expenses failed at tests: 2 tests failed after 6 rounds"
    )
    p = await ProposalStore(grow.kv).get(ref)
    assert p.status == ProposalStatus.FAILED and p.note == "tests: 2 tests failed after 6 rounds"


async def test_a_build_main_did_not_start_and_a_repeated_event_are_ignored(grow):
    await built(grow)
    says = len(grow.bus.events("out.say"))
    await grow.send("build.done", build_event(build_id="mctl-1"))  # started with mctl: not Main's to tell
    await grow.send("build.done", build_event(version="0.1.0"))
    await grow.send("build.done", build_event(version="0.1.0"))  # e.g. catch-up and the event both
    assert len(grow.bus.events("out.say")) == says + 1


async def test_on_start_builds_that_ended_while_main_was_down_are_told(grow):
    ref = await built(grow)
    grow.builder.records["b1"].update(status="failed", stage="verify", error="image build failed")
    again = MainService(grow.bus, ThreadStore(grow.kv), today=lambda: TODAY)  # a restarted Main on the same KV
    await again.catch_up()
    assert grow.bus.events("out.say")[-1][1]["text"] == "Building expenses failed at verify: image build failed"
    assert (await ProposalStore(grow.kv).get(ref)).status == ProposalStatus.FAILED


async def test_catch_up_leaves_a_running_build_alone(grow):
    ref = await built(grow)
    grow.builder.records["b1"]["status"] = "building"
    says = len(grow.bus.events("out.say"))
    await grow.svc.catch_up()
    assert len(grow.bus.events("out.say")) == says
    assert (await ProposalStore(grow.kv).get(ref)).status == ProposalStatus.BUILDING


async def test_catch_up_tries_again_until_the_builder_answers(grow):
    ref = await built(grow)
    grow.builder.records["b1"].update(status="done", version="0.1.0")
    real = next(h for s, h in grow.bus._subs if s == "rpc.build.get")
    calls = 0

    async def not_up_yet(msg: Message):  # compose starts Main and the builder together
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("no responders")
        await real(msg)

    grow.bus._subs = [(s, h) for s, h in grow.bus._subs if s != "rpc.build.get"] + [("rpc.build.get", not_up_yet)]
    await grow.svc.catch_up(attempts=3, wait=0)
    assert calls == 2
    assert (
        grow.bus.events("out.say")[-1][1]["text"]
        == "expenses is built and running (version 0.1.0). Ask me about it any time."
    )
    assert (await ProposalStore(grow.kv).get(ref)).status == ProposalStatus.DONE


async def test_catch_up_tells_a_build_the_builder_lost(grow):
    ref = await built(grow)
    del grow.builder.records["b1"]  # e.g. its KV was reset: it will never report this build
    await grow.svc.catch_up(attempts=1)
    assert (
        grow.bus.events("out.say")[-1][1]["text"]
        == "Building expenses failed at unknown: the builder has no record of it"
    )
    assert (await ProposalStore(grow.kv).get(ref)).status == ProposalStatus.FAILED


async def test_the_thread_stays_alternating_after_a_build_result(grow):
    await built(grow)
    await grow.send("build.done", build_event(version="0.1.0"))  # an assistant turn right after another
    grow.llm_script = [say("ok")]
    await grow.send("sense.chat", chat("thanks").data)
    roles = [m["role"] for m in grow.llm_requests[-1]["messages"]]
    assert roles[0] == "user" and all(a != b for a, b in zip(roles, roles[1:], strict=False))


def test_thread_messages_start_at_a_user_turn_and_merge_a_role_in_a_row():
    from main.thread import Thread, Turn
    from mycelium_sdk import Role

    turns = [
        (Role.ASSISTANT, "a0"),
        (Role.USER, "u1"),
        (Role.ASSISTANT, "a1"),
        (Role.ASSISTANT, "a2"),
        (Role.USER, "u2"),
    ]
    thread = Thread(channel="c", thread="t", turns=[Turn(role=r, text=x, ts="t") for r, x in turns])
    assert [(m.role, m.content) for m in thread.messages()] == [
        (Role.USER, "u1"),
        (Role.ASSISTANT, "a1\n\na2"),
        (Role.USER, "u2"),
    ]
