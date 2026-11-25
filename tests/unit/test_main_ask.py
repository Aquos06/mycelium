"""Who a "he" or "she" means: `remember` will not write to one of several people (or places) named just before, or,
with none of them named there, one of several that memory opened for the message, when Hansen's message names none
of them. It sends the planner to `ask`, with them as the choices."""

import re

import pytest

from main.tools import named_in, opened_in
from tests.unit.test_main import call, chat, say
from tests.unit.test_main_honest import make

NOTES = {
    "jason": "people/jason.md",
    "kevin": "people/kevin.md",
    "lin": "people/lin.md",
    "mei": "people/mei.md",
    "ramen-place-xinyi": "places/ramen-place-xinyi.md",
    "mycelium": "projects/mycelium.md",
    "thesis": "projects/thesis.md",
    "hansen": "hansen.md",
}


def memory(query: str) -> dict:
    """Recall by name, as memory's name rung does: each note whose name is in the query, and its `used.names`."""
    text = query.lower().replace("-", " ")
    named = [n for n in NOTES if re.search(rf"\b{re.escape(n.replace('-', ' '))}\b", text)]
    items = [{"note": NOTES[n], "why": f"{n} named in the query", "excerpt": ""} for n in named]
    return {"ok": True, "query": query, "items": items, "used": {"names": named}}


def near(*notes: str):
    """A memory that also opens `notes` for the message, as near in meaning, without the message naming them. The
    thread before is several lines, and only its names are found."""

    def reply(query: str) -> dict:
        pack = memory(query)
        if "\n" not in query:
            named = pack["used"]["names"]
            pack["items"] += [
                {"note": NOTES[n], "why": "similar (0.41)", "excerpt": ""} for n in notes if n not in named
            ]
        return pack

    return reply


@pytest.fixture
async def w():
    world = await make()
    world.recall_reply = memory
    return world


def promoted(note: str = "jason"):
    return call("remember", {"note": note, "fact": "got promoted"})


async def test_he_after_two_people_is_asked_not_guessed(w):
    w.llm_script = [
        say("Nice!"),
        promoted("jason"),
        call("ask", {"text": "Who got promoted?", "choices": ["Jason", "Kevin"]}, id="t2"),
    ]
    await w.send("sense.chat", chat("had lunch with jason and kevin today").data)
    await w.send("sense.chat", chat("yeah, remember that he just got promoted").data)

    assert w.remembered == []
    result = w.llm_requests[2]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result"
    assert "jason and kevin were all named just before" in result["content"]
    assert "Call `ask` with them as the choices" in result["content"]
    ((_, asked),) = w.bus.events("out.ask")
    assert asked["choices"] == ["Jason", "Kevin"]


async def test_the_tapped_answer_names_one_and_is_saved(w):
    w.llm_script = [
        say("Nice!"),
        promoted("jason"),
        call("ask", {"text": "Who got promoted?", "choices": ["Jason", "Kevin"]}, id="t2"),
        promoted("jason"),
        say("Saved."),
    ]
    await w.send("sense.chat", chat("had lunch with jason and kevin today").data)
    await w.send("sense.chat", chat("remember that he just got promoted").data)
    asked = len(w.recalled)
    await w.send("sense.chat", chat("Jason").data)

    assert [r["note"] for r in w.remembered] == ["jason"]
    assert len(w.recalled) == asked + 1  # the turn's own recall: memory is not asked again about the thread


async def test_one_person_named_before_is_the_one_he_means(w):
    w.llm_script = [say("Nice!"), promoted("jason"), say("Saved.")]
    await w.send("sense.chat", chat("had lunch with jason today").data)
    await w.send("sense.chat", chat("remember that he just got promoted").data)
    assert [r["note"] for r in w.remembered] == ["jason"]


async def test_a_person_and_a_place_named_before_are_not_mixed_up(w):
    w.llm_script = [say("Nice!"), promoted("jason"), say("Saved.")]
    await w.send("sense.chat", chat("had lunch with jason at the ramen place xinyi").data)
    await w.send("sense.chat", chat("remember that he just got promoted").data)
    assert [r["note"] for r in w.remembered] == ["jason"]


async def test_his_message_naming_one_saves_without_asking_memory_again(w):
    w.llm_script = [say("Nice!"), promoted("kevin"), say("Saved.")]
    await w.send("sense.chat", chat("had lunch with jason and kevin today").data)
    await w.send("sense.chat", chat("kevin got promoted, remember it").data)

    assert [r["note"] for r in w.remembered] == ["kevin"]
    assert len(w.recalled) == 2  # one per message


async def test_a_note_not_among_those_named_before_goes_through(w):
    """ "My sister got the job": Lin is the one person memory opened for it; Jason and Kevin before are not who it
    means."""
    w.recall_reply = near("lin")
    w.llm_script = [say("Nice!"), call("remember", {"note": "lin", "fact": "got the job"}), say("Saved.")]
    await w.send("sense.chat", chat("had lunch with jason and kevin today").data)
    await w.send("sense.chat", chat("my sister got the job!").data)
    assert [r["note"] for r in w.remembered] == ["lin"]


async def test_hansens_own_note_is_never_held_up(w):
    w.llm_script = [say("Nice!"), call("remember", {"note": "hansen", "fact": "got promoted"}), say("Saved.")]
    await w.send("sense.chat", chat("had lunch with jason and kevin today").data)
    await w.send("sense.chat", chat("and I got promoted!").data)
    assert [r["note"] for r in w.remembered] == ["hansen"]


async def test_the_first_message_of_a_thread_asks_memory_nothing_more(w):
    w.llm_script = [promoted("jason"), say("Saved.")]
    await w.send("sense.chat", chat("remember that he just got promoted").data)
    assert [r["note"] for r in w.remembered] == ["jason"] and len(w.recalled) == 1


async def test_memory_not_answering_about_the_thread_lets_the_write_go_on(w):
    w.recall_reply = lambda q: {"ok": False, "error": "index down"} if "\n" in q else memory(q)
    w.llm_script = [say("Nice!"), promoted("jason"), say("Saved.")]
    await w.send("sense.chat", chat("had lunch with jason and kevin today").data)
    await w.send("sense.chat", chat("remember that he just got promoted").data)
    assert [r["note"] for r in w.remembered] == ["jason"] and len(w.recalled) == 3


def test_named_in_is_the_notes_found_by_name_with_their_folders():
    pack = {
        "items": [
            {"note": "people/mei.md", "why": "小美 is an alias of mei"},
            {"note": "hansen.md", "why": "hansen named in the query"},
            {"note": "people/lin.md", "why": "similar to the question (0.41)"},  # near in meaning: not named
            {"note": "summaries/2026/11/23.md", "why": "yesterday"},
        ],
        "used": {"names": ["mei", "hansen"]},
    }
    assert named_in(pack) == {"mei": "people", "hansen": ""}
    assert named_in(None) == {} and named_in({"items": pack["items"]}) == {}
    assert opened_in(pack) == {"mei": "people", "hansen": "", "lin": "people", "23": "summaries/2026/11"}
    assert opened_in(None) == {}


async def test_memory_is_asked_about_the_thread_once_a_turn(w):
    w.llm_script = [
        say("Nice!"),
        call("remember", {"note": "jason", "fact": "got promoted"}, id="t1"),
        call("remember", {"note": "kevin", "fact": "got promoted"}, id="t2"),
        say("Who got promoted?"),
    ]
    await w.send("sense.chat", chat("had lunch with jason and kevin today").data)
    await w.send("sense.chat", chat("remember that he just got promoted").data)
    assert w.remembered == [] and len(w.recalled) == 3  # one per message, one about the thread


# ---- the first message: who memory opened for it ---------------------------------------------------------------


def got(note: str):
    return call("remember", {"note": note, "fact": "got the job"})


async def test_she_in_a_first_message_is_asked_when_two_people_come_up(w):
    w.recall_reply = near("mei", "lin")
    w.llm_script = [got("mei"), call("ask", {"text": "Who got the job?", "choices": ["Mei", "Lin"]}, id="t2")]
    await w.send("sense.chat", chat("she got the job!").data)

    assert w.remembered == []
    result = w.llm_requests[1]["messages"][-1]["content"][0]
    assert "mei and lin all came up in memory, so mei is a guess" in result["content"]
    ((_, asked),) = w.bus.events("out.ask")
    assert asked["choices"] == ["Mei", "Lin"]
    assert len(w.recalled) == 1  # nothing before it to ask memory about


async def test_one_person_in_memory_is_the_one_she_means(w):
    w.recall_reply = near("mei")
    w.llm_script = [got("mei"), say("Saved.")]
    await w.send("sense.chat", chat("she got the job!").data)
    assert [r["note"] for r in w.remembered] == ["mei"]


async def test_a_person_and_a_place_in_memory_are_not_mixed_up(w):
    w.recall_reply = near("mei", "ramen-place-xinyi")
    w.llm_script = [got("mei"), say("Saved.")]
    await w.send("sense.chat", chat("she got the job!").data)
    assert [r["note"] for r in w.remembered] == ["mei"]


async def test_the_one_named_just_before_is_who_he_means_whoever_memory_opened(w):
    w.recall_reply = near("jason", "kevin")
    w.llm_script = [say("Nice!"), promoted("jason"), say("Saved.")]
    await w.send("sense.chat", chat("had lunch with jason today").data)
    await w.send("sense.chat", chat("remember that he just got promoted").data)
    assert [r["note"] for r in w.remembered] == ["jason"]


async def test_a_sister_memory_has_no_name_for_is_asked_about(w):
    """The price: "my sister" says who, but memory found no name in it, and Mei came up as well as Lin."""
    w.recall_reply = near("mei", "lin")
    w.llm_script = [got("lin"), call("ask", {"text": "Who got the job?", "choices": ["Lin", "Mei"]}, id="t2")]
    await w.send("sense.chat", chat("my sister got the job!").data)
    assert w.remembered == [] and len(w.bus.events("out.ask")) == 1


async def test_a_sister_that_is_an_alias_of_lin_is_named(w):
    def reply(query: str) -> dict:
        pack = near("mei", "lin")(query)
        if "sister" in query:
            pack["used"]["names"].append("lin")
        return pack

    w.recall_reply = reply
    w.llm_script = [got("lin"), say("Saved.")]
    await w.send("sense.chat", chat("my sister got the job!").data)
    assert [r["note"] for r in w.remembered] == ["lin"]


async def test_notes_that_are_not_people_or_places_are_not_held_up(w):
    w.recall_reply = near("mycelium", "thesis")
    w.llm_script = [call("remember", {"note": "thesis", "fact": "finished the slides"}), say("Saved.")]
    await w.send("sense.chat", chat("finished the slides for it today").data)
    assert [r["note"] for r in w.remembered] == ["thesis"]
