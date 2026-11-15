"""A reply that comes back without words (a reasoning model's answer left in its thinking): Main asks once more, and if
it is still empty, says what the turn's calls did instead of sending nothing."""

import pytest

from main.service import EMPTY_REPLY, SAY_IT, _done_reply
from main.tools import AskModuleArgs, RemindArgs, ToolOutcome
from tests.unit.test_main import call, chat, say
from tests.unit.test_main_honest import make, plan


@pytest.fixture
async def w():
    return await make()


def replies(w) -> list[str]:
    return [d["text"] for _, d in w.bus.events("out.say")]


async def test_an_empty_reply_after_a_call_is_asked_again_and_its_answer_sent(w):
    w.llm_script = [call("remember", {"note": "hansen", "fact": "motorcycle broke down"}), say(""), say("Saved.")]
    await w.send("sense.chat", chat("my motorcycle broke down last saturday").data)

    assert replies(w) == ["Saved."]
    assert len(w.llm_requests) == 3 and len(w.remembered) == 1
    last = w.llm_requests[2]["messages"][-1]  # the note after the tool's result, in the same message
    assert last["role"] == "user" and [b["type"] for b in last["content"]] == ["tool_result", "text"]
    assert last["content"][1]["text"] == SAY_IT
    trace = plan(w)
    assert trace["empty_check"] is True and trace["rounds"] == 3 and trace["error"] is None


async def test_an_empty_first_answer_gets_the_note_after_hansens_message(w):
    w.llm_script = [say("\n\n"), say("Hi!")]
    await w.send("sense.chat", chat("hello").data)

    assert replies(w) == ["Hi!"]
    last = w.llm_requests[1]["messages"][-1]
    assert last["role"] == "user" and [b["text"] for b in last["content"]][-1] == SAY_IT
    assert "hello" in last["content"][0]["text"]


async def test_a_call_made_on_the_second_ask_is_not_run(w):
    w.llm_script = [
        call("remember", {"note": "hansen", "fact": "motorcycle broke down"}),
        say(""),
        call("remember", {"note": "hansen", "fact": "motorcycle broke down"}, text="Saved."),
    ]
    await w.send("sense.chat", chat("my motorcycle broke down").data)

    assert len(w.remembered) == 1  # once
    assert replies(w) == ["Saved."]


async def test_still_empty_it_says_what_the_calls_did(w):
    w.llm_script = [
        call("remember", {"note": "hansen", "fact": "stretches daily"}, id="t1"),
        call("remind", {"text": "Time to stretch.", "in_minutes": 20}, id="t2"),
        say(""),
        say(""),
    ]
    await w.send("sense.chat", chat("i stretch daily, remind me in 20 minutes").data)

    (reply,) = replies(w)
    assert reply.startswith("Saved to memory. Reminder set for ") and reply.endswith(": Time to stretch.")
    assert plan(w)["empty_check"] is True


async def test_still_empty_with_nothing_done_it_says_so(w):
    w.llm_script = [say(""), say("")]
    await w.send("sense.chat", chat("how much did i spend?").data)
    assert replies(w) == [EMPTY_REPLY]


async def test_a_failed_second_ask_is_no_failed_turn(w):
    w.llm_script = [
        call("remember", {"note": "hansen", "fact": "motorcycle broke down"}),
        say(""),
        {"ok": False, "error": "gateway: timed out after 120s"},
    ]
    await w.send("sense.chat", chat("my motorcycle broke down").data)

    assert replies(w) == ["Saved to memory."]
    assert plan(w)["error"] is None and len(plan(w)["llm_calls"]) == 2


async def test_an_empty_reply_on_the_last_round_is_asked_again_too(w):
    w.svc.max_rounds = 2
    w.llm_script = [call("remember", {"note": "hansen", "fact": "x"}), say(""), say("Saved.")]
    await w.send("sense.chat", chat("remember x").data)
    assert replies(w) == ["Saved."]


async def test_a_card_with_no_words_before_it_is_not_asked_again(w):
    w.llm_script = [call("ask", {"text": "Which Mei?", "choices": ["Mei Lin", "Mei Chen"]})]
    await w.send("sense.chat", chat("mei is moving").data)

    assert len(w.llm_requests) == 1 and plan(w)["empty_check"] is False
    assert [d["text"] for _, d in w.bus.events("out.ask")] == ["Which Mei?"]


async def test_a_worded_reply_is_never_asked_again(w):
    w.llm_script = [say("Hi!")]
    await w.send("sense.chat", chat("hello").data)
    assert len(w.llm_requests) == 1 and plan(w)["empty_check"] is False


def outcome(name: str, result: dict, args=None, **input) -> ToolOutcome:
    return ToolOutcome(name=name, input=input, args=args, result=result)


def test_the_fallback_tells_writes_once_and_puts_what_it_showed_last():
    add = AskModuleArgs(module="expenses", action="add", args={"amount": 85})
    tools = [
        outcome("show", {"ok": True}),
        outcome("remember", {"ok": True}),
        outcome("remember", {"ok": True}),
        outcome("ask_module", {"ok": True}, add),
        outcome("ask_module", {"ok": True}, AskModuleArgs(module="expenses", action="summary")),  # a read
        outcome("remind", {"ok": False, "error": "has passed"}, RemindArgs(text="late", in_minutes=1)),
        outcome(
            "remind",
            {"ok": True, "when": "Fri 2026-11-20 09:00", "repeat": "every week"},
            RemindArgs(text="Time to pay the rent. ", at="2026-11-20 09:00", repeat="weekly"),
        ),
        outcome("cancel_reminder", {"ok": True, "cancelled": "Call mom.", "was_due": "Sat 2026-11-21 10:00"}),
    ]
    assert _done_reply(tools) == (
        "Saved to memory. Sent to expenses (add). Reminder set for Fri 2026-11-20 09:00, every week: Time to pay the "
        "rent. Reminder cancelled: Call mom. Here it is:"
    )
    assert _done_reply([outcome("recall", {"ok": True, "hits": []})]) == EMPTY_REPLY
