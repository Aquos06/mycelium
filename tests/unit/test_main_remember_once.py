"""The same fact twice in one turn is written once: the model sometimes calls `remember` again with what it has just
saved, the same words or others, and memory keeps every line it is sent."""

import pytest

from main.tools.memory import same_fact
from tests.unit.test_main import call, chat, say
from tests.unit.test_main_honest import make

BOOK = "finished reading Project Hail Mary and loved it (2026-11-02)"
BOOK_AGAIN = "finished reading Project Hail Mary last night and loved it"


@pytest.fixture
async def w():
    return await make()


def remember(note: str, fact: str, id: str = "t1", **more):
    return call("remember", {"note": note, "fact": fact, **more}, id=id)


def both(*calls: dict) -> dict:
    """One planner reply with several calls."""
    first = calls[0]
    return {**first, "tool_calls": [c["tool_calls"][0] for c in calls]}


def facts(w) -> list[tuple[str, str]]:
    return [(r["note"], r["fact"]["text"]) for r in w.remembered if "fact" in r]


async def test_a_fact_said_again_in_other_words_is_written_once(w):
    w.llm_script = [
        remember("hansen", BOOK, day="2026-11-02"),
        remember("hansen", BOOK_AGAIN, id="t2", day="2026-11-02"),
        say("Saved."),
    ]
    await w.send("sense.chat", chat("finished project hail mary last night, loved it").data)

    assert facts(w) == [("hansen", BOOK)]
    again = w.llm_requests[2]["messages"][-1]["content"][0]["content"]
    assert '"ok": true' in again and '"already_saved"' in again
    assert w.bus.events("out.say")[0][1]["text"] == "Saved."


async def test_the_same_call_twice_in_one_reply_is_written_once(w):
    w.llm_script = [
        both(
            remember("mei", "is moving to Tainan in December"), remember("mei", "is moving to Tainan in December", "t2")
        ),
        say("Saved."),
    ]
    await w.send("sense.chat", chat("mei is moving to tainan in december").data)
    assert facts(w) == [("mei", "is moving to Tainan in December")]


async def test_two_facts_about_one_person_are_both_written(w):
    w.llm_script = [
        both(remember("mei", "is moving to Tainan in December"), remember("mei", "got a job at a design studio", "t2")),
        say("Saved both."),
    ]
    await w.send("sense.chat", chat("mei is moving to tainan in december, she got a job at a design studio").data)
    assert facts(w) == [("mei", "is moving to Tainan in December"), ("mei", "got a job at a design studio")]


async def test_the_same_fact_about_two_people_is_written_to_each(w):
    w.llm_script = [
        both(remember("mei", "is coming on the Tainan trip"), remember("lin", "is coming on the Tainan trip", "t2")),
        say("Saved."),
    ]
    await w.send("sense.chat", chat("mei and lin are coming on the tainan trip").data)
    assert facts(w) == [("mei", "is coming on the Tainan trip"), ("lin", "is coming on the Tainan trip")]


async def test_the_same_words_about_two_days_are_two_facts(w):
    w.llm_script = [
        both(
            remember("hansen", "climbed at the gym", day="2026-11-01"),
            remember("hansen", "climbed at the gym", "t2", day="2026-11-02"),
        ),
        say("Saved."),
    ]
    await w.send("sense.chat", chat("climbed saturday and sunday").data)
    assert len(facts(w)) == 2


async def test_a_fact_said_again_next_turn_is_written_again(w):
    """Only one turn is looked at: a fact told again later is Hansen's to repeat."""
    w.llm_script = [
        remember("mei", "is moving to Tainan"),
        say("Saved."),
        remember("mei", "is moving to Tainan"),
        say("Saved."),
    ]
    await w.send("sense.chat", chat("mei is moving to tainan").data)
    await w.send("sense.chat", chat("did I tell you mei is moving to tainan?").data)
    assert len(facts(w)) == 2


async def test_a_save_that_failed_is_tried_again(w):
    w.remember_reply = {"ok": False, "error": "vault busy"}
    w.llm_script = [remember("mei", "is moving to Tainan"), remember("mei", "is moving to Tainan", "t2"), say("Saved.")]
    await w.send("sense.chat", chat("mei is moving to tainan").data)
    assert len(w.remembered) == 2


async def test_a_fact_said_again_with_a_new_alias_sends_only_the_alias(w):
    w.llm_script = [
        remember("mei", "is moving to Tainan"),
        remember("mei", "is moving to Tainan", "t2", aliases=["小美"]),
        say("Saved."),
    ]
    await w.send("sense.chat", chat("mei (小美) is moving to tainan").data)
    assert facts(w) == [("mei", "is moving to Tainan")]
    assert w.remembered[1] == {"note": "mei", "source": "hansen", "aliases": ["小美"]}


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        (BOOK, BOOK_AGAIN, True),
        ("is moving to Tainan in December", "Is moving to Tainan in December.", True),
        ("早餐花了85元", "早餐花了85元", True),
        ("ran 5 km", "ran 10 km", False),
        ("likes the shoyu ramen", "likes the miso ramen", False),
        ("moved to Tainan", "moved to Tainan in December", False),
        ("spent 120 on lunch", "spent 120 on lunch with Jason at the ramen place", False),
        ("早餐花了85元", "午餐花了85元", False),
    ],
)
def test_same_fact(a, b, same):
    assert same_fact(a, b) is same
