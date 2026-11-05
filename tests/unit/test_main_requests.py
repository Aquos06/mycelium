"""Main calls a module from what its manifest says each request takes: the prompt shows the described requests,
entries go to a module's `add` rather than memory, specs Main drafts ask for described requests and `add`, and a
model that was only slow is not called unreachable."""

import pytest

from main.prompt import render_modules
from main.schemas import ModuleInfo
from main.service import MODEL_DOWN_REPLY, MODEL_SLOW_REPLY, MainService
from main.thread import ThreadStore
from main.tools import ProposeArgs
from mycelium_sdk import InMemoryBus, InMemoryKV, RequestSpec
from tests.unit.test_main import TODAY, World, call, chat, say

ADD = {
    "description": "Store one expense.",
    "params": {"amount": "number", "description": "string", "day": "optional date"},
    "returns": {"id": "number"},
}
SUMMARY = {"description": "Totals and count, all time when no dates are given.", "params": {"from": "optional date"}}
EXPENSES = {
    "name": "expenses",
    "status": "running",
    "manifest": {
        "purpose": "Tracks Hansen's spending.",
        "requests": ["add", "summary", "history"],
        "request_specs": {"add": ADD, "summary": SUMMARY, "history": {"description": "x"}},  # history's is bad
    },
}


@pytest.fixture
async def w():
    bus = InMemoryBus()
    world = World(bus, [])
    world.modules = [EXPENSES]
    await world.start()
    world.svc = MainService(bus, ThreadStore(InMemoryKV()), today=lambda: TODAY, tz="Asia/Taipei")
    await world.svc.start()
    return world


# ---- the module list ----------------------------------------------------------------------------------


def test_described_requests_show_their_fields_and_what_comes_back():
    info = ModuleInfo(
        name="expenses",
        purpose="Tracks Hansen's spending.",
        requests=["expenses.add", "expenses.history"],
        specs={"expenses.add": RequestSpec.model_validate(ADD)},
    )
    assert render_modules([info]).splitlines() == [
        "- expenses: Tracks Hansen's spending. Requests (send the fields shown in `args`):",
        "  - expenses.add {amount: number, description: string, day: optional date}: Store one expense. "
        "Returns {id: number}.",
        "  - expenses.history: not described",
    ]


def test_a_module_that_is_not_running_is_said_so_after_the_running_ones():
    """Hansen's thread still said "expenses is built and running"; without this line the model believed it."""
    hello = ModuleInfo(name="hello", purpose="Counts chat messages.", requests=["hello.stats"])
    gone = ModuleInfo(name="expenses", purpose="Tracks spending.", requests=["expenses.add"], status="retired")
    assert render_modules([hello, gone]).splitlines() == [
        "- hello: Counts chat messages. Requests: hello.stats",
        "Not running now (an earlier message may say otherwise; do not call them): expenses (retired)",
    ]
    assert render_modules([gone]).splitlines()[0] == "(none running)"


async def test_a_retired_module_is_listed_as_not_running_and_its_calls_refused(w):
    w.modules = [*w.modules, {"name": "groceries", "status": "retired", "manifest": {"purpose": "Tracks food."}}]
    w.llm_script = [call("ask_module", {"module": "groceries", "action": "add"}), say("It is not running.")]
    await w.send("sense.chat", chat("I want to track my groceries").data)
    assert "do not call them): groceries (retired)" in w.llm_requests[0]["system"]
    (outcome,) = w.bus.events("trace.plan")[0][1]["tools"]
    assert outcome["result"]["error"].startswith("no module 'groceries' is running (running: expenses)")


async def test_a_module_used_in_this_chat_that_stopped_is_noted_before_the_message(w):
    """The thread said "expenses is built and running"; the model believed it until told in the newest message."""
    w.llm_script = [call("ask_module", {"module": "expenses", "action": "summary"}), say("4210 this month.")]
    await w.send("sense.chat", chat("whats my expense").data)
    w.modules = [{**EXPENSES, "status": "retired"}]
    w.llm_script = [say("expenses is not running; want me to propose it again?")]
    await w.send("sense.chat", chat("I want to track my expenses").data)
    last = w.llm_requests[-1]["messages"][-1]["content"]
    assert last.startswith("(A note from Main's code, not from Hansen: since earlier in this chat, these modules")
    assert "stopped running: expenses (retired)." in last and last.endswith("\n\nI want to track my expenses")
    turns = (await w.svc.store.load("telegram", "123")).turns
    assert turns[-2].text == "I want to track my expenses"  # the note is never kept


async def test_no_note_while_the_module_runs_or_for_a_call_that_was_refused(w):
    w.llm_script = [
        call("ask_module", {"module": "expenses", "action": "summary"}),
        call("ask_module", {"module": "groceries", "action": "add"}, id="t2"),  # refused: never ran
        say("ok"),
        say("ok"),
    ]
    await w.send("sense.chat", chat("whats my expense").data)
    await w.send("sense.chat", chat("thanks").data)
    assert w.llm_requests[-1]["messages"][-1]["content"] == "thanks"


def test_a_module_with_named_requests_only_keeps_its_one_line():
    info = ModuleInfo(name="hello", purpose="Counts chat messages.", requests=["hello.stats"])
    assert render_modules([info]) == "- hello: Counts chat messages. Requests: hello.stats"


async def test_main_reads_the_specs_rpc_sys_list_serves_and_skips_a_bad_one(w):
    w.llm_script = [say("ok")]
    await w.send("sense.chat", chat("whats my expense").data)
    system = w.llm_requests[0]["system"]
    assert "  - expenses.add {amount: number, description: string, day: optional date}: Store one expense." in system
    assert "  - expenses.summary {from: optional date}: Totals and count, all time when no dates are given." in system
    assert "  - expenses.history: not described" in system  # its description was too short to keep


async def test_the_policy_sends_entries_to_a_module_and_asks_for_all_of_it(w):
    w.llm_script = [say("ok")]
    await w.send("sense.chat", chat("spent 85 on breakfast").data)
    system = w.llm_requests[0]["system"]
    assert "a module takes through a request like `add`" in system and "not in memory" in system
    assert "ask for all of it, not only today" in system


# ---- a slow model is not an unreachable one --------------------------------------------------------------


@pytest.mark.parametrize(
    "error, reply",
    [
        ("vllm: timed out after 90s", MODEL_SLOW_REPLY),
        ("gateway unreachable: no responders", MODEL_DOWN_REPLY),
        ("budget exceeded: $30.00 of $30.00 this month", MODEL_DOWN_REPLY),
    ],
)
async def test_the_failure_reply_says_whether_the_model_was_slow(w, error, reply):
    w.llm_script = [{"ok": False, "error": error}]
    await w.send("sense.chat", chat("put all of that in the module").data)
    assert w.bus.events("out.say")[0][1]["text"] == reply


# ---- a module that is not running is said at once ---------------------------------------------------------


async def test_a_module_that_is_not_running_is_refused_without_waiting_on_the_bus(w):
    """Hansen's thread: the old expenses was retired, Main called expenses.add 7 times, each waiting 10 s."""
    w.llm_script = [
        call("ask_module", {"module": "groceries", "action": "add", "args": {"amount": 112}}),
        say("There is no groceries module running yet."),
    ]
    await w.send("sense.chat", chat("put my earlier expenses into the module").data)
    (outcome,) = w.bus.events("trace.plan")[0][1]["tools"]
    assert outcome["result"] == {
        "ok": False,
        "error": "no module 'groceries' is running (running: expenses). Tell Hansen; do not retry it.",
    }
    assert not w.bus.events("rpc.mod.groceries.add")  # never asked on the bus


async def test_a_request_the_module_does_not_declare_is_refused_with_its_list(w):
    w.llm_script = [call("ask_module", {"module": "expenses", "action": "stats"}), say("ok")]
    await w.send("sense.chat", chat("whats my expense").data)
    (outcome,) = w.bus.events("trace.plan")[0][1]["tools"]
    assert outcome["result"]["error"] == "expenses has no request 'stats'; its requests: add, summary, history"


async def test_with_the_supervisor_silent_a_call_still_goes_to_the_module(w):
    w.bus._subs = [(s, h) for s, h in w.bus._subs if s != "rpc.sys.list"]  # type: ignore[attr-defined]
    w.llm_script = [call("ask_module", {"module": "expenses", "action": "summary"}), say("ok")]
    await w.send("sense.chat", chat("whats my expense").data)
    (outcome,) = w.bus.events("trace.plan")[0][1]["tools"]
    assert outcome["result"]["ok"] is True  # nobody said it is not running: ask it


async def test_steps_used_up_say_what_failed_last(w):
    w.svc.max_rounds = 2
    w.llm_script = [
        call("ask_module", {"module": "groceries", "action": "add"}),
        call("ask_module", {"module": "groceries", "action": "add"}, id="t2"),
    ]
    await w.send("sense.chat", chat("put it in").data)
    text = w.bus.events("out.say")[0][1]["text"]
    assert text.startswith("I couldn't finish this: I used all my steps without getting there.")
    assert "no module 'groceries' is running" in text and MODEL_DOWN_REPLY not in text


# ---- the specs Main drafts ------------------------------------------------------------------------------

TRACKER = {
    "name": "expenses",
    "purpose": "Tracks Hansen's spending and answers totals.",
    "need": "Hansen logs what he spends and wants totals.",
    "behaviour": ["one entry: amount, description, day", "totals by day and description"],
    "answers": [
        "add {amount: number, description: string, day: optional date}: store one expense",
        "`summary` {from: optional date, to: optional date}: totals and count, all time by default",
        "history: every expense, newest first",
    ],
}


def test_answers_keep_their_fields_though_the_fields_have_colons():
    args = ProposeArgs.model_validate(TRACKER)
    assert args.requests() == [
        ("add", "{amount: number, description: string, day: optional date}", "store one expense"),
        ("summary", "{from: optional date, to: optional date}", "totals and count, all time by default"),
        ("history", "", "every expense, newest first"),
    ]
    assert args.takes_entries()


def test_a_tracking_spec_says_entries_come_through_add_and_requests_are_described():
    spec = ProposeArgs.model_validate(TRACKER).spec()
    assert "- answers `add` {amount: number, description: string, day: optional date}: store one expense" in spec
    assert "the module does not parse chat messages itself" in spec
    assert "Every request is described in manifest.yaml (description, params, returns)" in spec
    assert "Then I can ask it: add, summary, history." in ProposeArgs.model_validate(TRACKER).card()


def test_a_spec_without_add_does_not_claim_entries_come_from_main():
    plain = {**TRACKER, "answers": ["summary: totals for a date range"]}
    spec = ProposeArgs.model_validate(plain).spec()
    assert "does not parse chat" not in spec and "Every request is described" in spec


def test_lines_written_with_an_escaped_newline_are_still_one_line_each():
    """Hansen's expenses-v2 spec: the model sent each list as one item with `\\n` in it, so the three requests were
    one answer line and the spec read "store one expense entry\\nsummary {...}"."""
    args = ProposeArgs.model_validate(
        {
            **TRACKER,
            "behaviour": ["one entry holds: date, amount\\n- summarizes: totals by category"],
            "answers": ["add {amount: number}: store one expense entry\\nsummary {from: optional date}: totals"],
        }
    )
    assert args.behaviour == ["one entry holds: date, amount", "summarizes: totals by category"]
    assert [req for req, _, _ in args.requests()] == ["add", "summary"]
    assert "\\n" not in args.spec()
