"""Main says what it did, and only that: the thread replays each turn's tool calls and dates each message, a reply
that claims a save no `remember` made is asked again, and the prompt lists the modules already offered."""

from zoneinfo import ZoneInfo

import pytest

from main.proposals import Proposal, ProposalStatus
from main.service import CLAIM, RECHECK, MainService
from main.thread import INPUT_KEPT, RESULT_KEPT, Thread, ThreadStore, Turn, TurnCall
from mycelium_sdk import InMemoryBus, InMemoryKV, Role
from tests.unit.test_main import TODAY, World, call, chat, dated, say

MOTORCYCLE = "tomorrow i need to spend 12000 for the motorcycle, the gas pump broke"


class LockedVault(World):
    """Memory that refuses every write."""

    async def _remember(self, msg):
        await msg.respond({"ok": False, "error": "vault locked"})


async def make(world_cls: type[World] = World) -> World:
    bus = InMemoryBus()
    world = world_cls(bus, [])
    await world.start()
    world.svc = MainService(bus, ThreadStore(InMemoryKV(), max_turns=10), today=lambda: TODAY, tz="Asia/Taipei")
    await world.svc.start()
    return world


@pytest.fixture
async def w():
    return await make()


def plan(world: World) -> dict:
    return world.bus.events("trace.plan")[-1][1]


# ---- the thread shows what was done -------------------------------------------------------------------


async def test_a_turns_tool_calls_are_replayed_in_the_next_turn(w):
    w.llm_script = [call("remember", {"note": "mei", "fact": "likes ramen"}), say("Saved."), say("You're welcome.")]
    first = chat("mei likes ramen")
    await w.send("sense.chat", first.data)
    await w.send("sense.chat", chat("thanks").data)

    sent = w.llm_requests[2]["messages"]  # the second turn's only round
    assert sent[0] == {"role": "user", "content": dated(first)}
    (use,) = sent[1]["content"]
    assert sent[1]["role"] == "assistant" and use == {
        "type": "tool_use",
        "id": use["id"],
        "name": "remember",
        "input": {"note": "mei", "fact": "likes ramen"},
    }
    (result,) = sent[2]["content"]
    assert result["tool_use_id"] == use["id"] and '"ok": true' in result["content"]
    assert sent[3:] == [{"role": "assistant", "content": "Saved."}, {"role": "user", "content": "thanks"}]
    turns = (await w.svc.store.load("telegram", "123")).turns
    assert [c.name for c in turns[1].calls] == ["remember"] and turns[3].calls == []


async def test_a_rejected_call_is_not_kept_in_the_thread(w):
    w.llm_script = [call("remember", {"fact": "no note"}), say("Sorry, I couldn't save that.")]
    await w.send("sense.chat", chat("remember this").data)
    assert (await w.svc.store.load("telegram", "123")).turns[1].calls == []


def test_a_kept_call_is_cut_short():
    long = TurnCall.of("propose_module", {"need": "x" * 1000, "behaviour": ["a"]}, {"ok": True, "spec": "y" * 1000})
    assert len(long.input["need"]) == INPUT_KEPT + 1 and long.input["behaviour"] == ["a"]
    assert len(long.result) == RESULT_KEPT


def test_each_message_is_dated_in_mains_time_zone():
    thread = Thread(
        channel="web",
        thread="t",
        turns=[
            Turn(role=Role.USER, text="today i spent 112", ts="2026-10-26T20:00:00+00:00"),  # 04:00 next day in Taipei
            Turn(role=Role.ASSISTANT, text="Logged.", ts="2026-10-26T20:00:05+00:00"),
            Turn(role=Role.USER, text="no time on this one", ts="yesterday"),
        ],
    )
    assert [m.content for m in thread.messages(ZoneInfo("Asia/Taipei"))] == [
        "[Tue 2026-10-27] today i spent 112",
        "Logged.",
        "no time on this one",
    ]


def test_a_build_result_after_a_tool_turn_keeps_roles_alternating():
    calls = [TurnCall(name="remember", input={"note": "mei"}, result='{"ok": true}')]
    thread = Thread(
        channel="web",
        thread="t",
        turns=[
            Turn(role=Role.USER, text="mei likes ramen", ts="2026-11-01T10:00:00+08:00"),
            Turn(role=Role.ASSISTANT, text="Saved.", ts="2026-11-01T10:00:01+08:00", calls=calls),
            Turn(role=Role.ASSISTANT, text="expenses is built and running.", ts="2026-11-01T11:00:00+08:00"),
        ],
    )
    roles = [m.role for m in thread.messages()]
    assert roles == [Role.USER, Role.ASSISTANT, Role.USER, Role.ASSISTANT]
    assert thread.messages()[-1].content == "Saved.\n\nexpenses is built and running."


# ---- a claimed save is checked ------------------------------------------------------------------------


async def test_a_reply_that_claims_a_save_without_remember_is_asked_again(w):
    w.llm_script = [
        say("Got it all saved."),
        call("remember", {"note": "motorcycle", "fact": "needs a new gas pump, 12000"}),
        say("Saved: the gas pump, 12000."),
    ]
    await w.send("sense.chat", chat(MOTORCYCLE).data)

    assert w.llm_requests[1]["messages"][-2:] == [
        {"role": "assistant", "content": "Got it all saved."},
        {"role": "user", "content": RECHECK},
    ]
    assert len(w.remembered) == 1
    assert w.bus.events("out.say")[0][1]["text"] == "Saved: the gas pump, 12000."
    assert plan(w)["claim_check"] is True
    turns = (await w.svc.store.load("telegram", "123")).turns
    assert turns[1].text == "Saved: the gas pump, 12000."  # the first reply never reaches the thread


async def test_the_check_asks_once(w):
    w.llm_script = [say("Saved."), say("I didn't save anything, I only read it.")]
    await w.send("sense.chat", chat(MOTORCYCLE).data)
    assert len(w.llm_requests) == 2
    assert w.bus.events("out.say")[0][1]["text"] == "I didn't save anything, I only read it."


async def test_a_claim_in_chinese_is_checked_too(w):
    w.llm_script = [say("好，記下了。"), say("好的。")]
    await w.send("sense.chat", chat("明天修車要12000").data)
    assert plan(w)["claim_check"] is True


@pytest.mark.parametrize(
    "reply",
    [
        "I've remembered the motorcycle repair situation:\n- Broke down last Saturday\n\nGot it all saved.",
        "Got it. I've logged your spending for today: 112 for dinner and 25 for drinks.",
        "Logged: 152 for dinner today.",
        "Noted. Mei is pregnant, due in May.",
        "Saved: the gas pump, 12000.",
        "That's noted for next week.",
        "已記住：小美下個月要搬去台南。",
    ],
)
def test_claims_of_a_save_are_recognised(reply):
    assert CLAIM.search(reply)


@pytest.mark.parametrize(
    "reply",
    [  # what the benchmark's recall and ask_module answers said: no save claimed
        "I don't have any information about your sister in my memory. I just searched and found nothing.",
        "Nothing about your landlord is saved yet. Want me to remember it?",
        "I can remember it for you if you tell me the dentist's name.",
        "The climbing module logged 12 sessions this month, up from 9.",
        "我沒說我存了什麼。expenses 模組的資料顯示這個月花了 4210。",
        "I didn't save anything, I only read it.",
    ],
)
def test_denials_offers_and_a_modules_numbers_are_not_claims(reply):
    assert not CLAIM.search(reply)


@pytest.mark.parametrize("reply", ["Hi! What can I do?", "Mei likes ramen, from what I have."])
async def test_a_reply_that_claims_nothing_goes_out_as_it_is(w, reply):
    w.llm_script = [say(reply)]
    await w.send("sense.chat", chat("hi").data)
    assert len(w.llm_requests) == 1 and plan(w)["claim_check"] is False


async def test_a_save_that_remember_made_is_not_checked(w):
    w.llm_script = [call("remember", {"note": "mei", "fact": "likes ramen"}), say("Saved.")]
    await w.send("sense.chat", chat("mei likes ramen").data)
    assert len(w.llm_requests) == 2 and plan(w)["claim_check"] is False


async def test_a_save_whose_remember_failed_is_checked():
    w = await make(LockedVault)
    w.llm_script = [call("remember", {"note": "mei", "fact": "likes ramen"}), say("Saved."), say("I couldn't save it.")]
    await w.send("sense.chat", chat("mei likes ramen").data)
    assert plan(w)["claim_check"] is True
    assert w.bus.events("out.say")[0][1]["text"] == "I couldn't save it."


async def test_a_module_that_hears_the_chat_may_have_logged_it(w):
    w.modules = [
        {
            "name": "expenses",
            "status": "running",
            "manifest": {"purpose": "Tracks spending.", "requests": ["summary"], "subscribes": ["sense.chat"]},
        }
    ]
    w.llm_script = [say("expenses logged it: dinner 350.")]
    await w.send("sense.chat", chat("dinner 350").data)
    assert len(w.llm_requests) == 1 and plan(w)["claim_check"] is False


# ---- what was offered is in the prompt ----------------------------------------------------------------


async def test_the_prompt_lists_modules_offered_and_not_running(w):
    def proposal(i: int, name: str, status: ProposalStatus) -> Proposal:
        return Proposal(
            id=f"p{i}",
            name=name,
            purpose=f"Tracks {name}.",
            spec=f"# Spec: {name}\n",
            channel="web",
            thread="web",
            status=status,
            created=f"2026-11-0{i}T10:00:00+00:00",
            decided=None if status == ProposalStatus.PROPOSED else f"2026-11-0{i}T11:00:00+00:00",
        )

    await w.svc.proposals.create(proposal(1, "expenses", ProposalStatus.PROPOSED))
    await w.svc.proposals.create(proposal(2, "sleep", ProposalStatus.DECLINED))
    await w.svc.proposals.create(proposal(3, "weight", ProposalStatus.FAILED))
    await w.svc.proposals.create(proposal(4, "water", ProposalStatus.DONE))  # running: in the module list instead
    w.llm_script = [say("ok")]
    await w.send("sense.chat", chat("lunch was 120").data)

    system = w.llm_requests[0]["system"]
    offered = system.split("Offered (modules proposed to Hansen, not running):\n", 1)[1]
    assert offered.splitlines() == [
        "- weight: Tracks weight. (its build failed on 2026-11-03: offer it again only if he asks for it)",
        "- sleep: Tracks sleep. (he chose Not now on 2026-11-02: do not offer it again unless he asks for it)",
        "- expenses: Tracks expenses. (offered 2026-11-01, waiting for his Build it: do not offer it again, the card "
        "is there)",
    ]


async def test_nothing_offered_says_so(w):
    w.llm_script = [say("ok")]
    await w.send("sense.chat", chat("hi").data)
    assert w.llm_requests[0]["system"].endswith("not running):\n(none)")
