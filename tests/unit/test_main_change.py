"""Main changes a module the builder grew: change_module -> a change proposal stored -> its card (Change it /
Not now) -> a tap -> rpc.build.start with `change` -> the result in the thread that asked. The module keeps its
data and runs as it is until the new version deploys; only grown modules can be changed."""

import pytest

from main.prompt import render_modules, render_proposals
from main.proposals import Proposal, ProposalKind, ProposalStatus, ProposalStore
from main.schemas import ModuleInfo
from main.service import CHANGE_IT, NOT_NOW, MainService
from main.thread import ThreadStore
from main.tools import ChangeArgs, ProposeArgs
from mycelium_sdk import InMemoryBus, InMemoryKV
from tests.unit.test_main import TODAY, World, call, chat, say
from tests.unit.test_main_grow import EXPENSES, Builder, build_event, tap

HELLO = {"name": "hello", "status": "running", "manifest": {"purpose": "Counts chat messages.", "requests": ["stats"]}}
GROWN = {
    "name": "expenses",
    "status": "running",
    "version": "0.1.0",
    "manifest": {"purpose": "Tracks Hansen's spending.", "version": "0.1.0", "requests": ["add", "summary"]},
}
CATEGORY = {
    "module": "expenses",
    "change": [
        "`add` also takes a category: add {amount: number, description: string, category: optional string}",
        "`summary` gives totals per category",
    ],
    "why": "Hansen wants to see how much goes to food and how much to transport.",
}
CHANGE_TEXT = (
    "Why: Hansen wants to see how much goes to food and how much to transport.\n\n"
    "- `add` also takes a category: add {amount: number, description: string, category: optional string}\n"
    "- `summary` gives totals per category"
)


@pytest.fixture
async def chg():
    bus = InMemoryBus()
    w = World(bus, [])
    w.modules = [HELLO, GROWN]
    w.grown = ["expenses"]
    await w.start()
    w.builder = Builder(bus)
    await w.builder.start()
    w.kv = InMemoryKV()
    w.svc = MainService(bus, ThreadStore(w.kv, max_turns=10), today=lambda: TODAY, build_timeout=0.2)
    await w.svc.start()
    return w


async def offer(w, args=CATEGORY) -> dict:
    """One turn that ends in a change card; returns it (out.ask)."""
    w.llm_script = [call("change_module", args, text="I can change it for that.")]
    await w.send("sense.chat", chat("can expenses keep a category too? food, transport").data)
    asks = w.bus.events("out.ask")
    assert asks, "a change should end in a card"
    return asks[-1][1]


async def changing(w) -> str:
    card = await offer(w)
    await w.send("sense.feedback", tap(card["ref"], CHANGE_IT))
    return card["ref"]


# ---- what the planner sees ---------------------------------------------------------------------------


def test_a_grown_module_is_marked_with_its_version_and_a_hand_written_one_is_not():
    hello = ModuleInfo(name="hello", purpose="Counts chat messages.", requests=["hello.stats"])
    grown = ModuleInfo(
        name="expenses", purpose="Tracks spending.", requests=["expenses.add"], grown=True, version="0.1.0"
    )
    assert render_modules([hello, grown]).splitlines() == [
        "- hello: Counts chat messages. Requests: hello.stats",
        "- expenses (grown, v0.1.0): Tracks spending. Requests: expenses.add",
    ]


async def test_main_reads_which_modules_are_grown_and_the_policy_says_what_to_do_with_them(chg):
    chg.llm_script = [say("ok")]
    await chg.send("sense.chat", chat("the summary is wrong").data)
    system = chg.llm_requests[0]["system"]
    assert "- expenses (grown, v0.1.0): Tracks Hansen's spending." in system
    assert "- hello: Counts chat messages." in system
    assert "Use `change_module` when a module marked grown does something wrong" in system
    assert "Do not `propose_module` a second module for what a running one should do" in system


def test_change_lines_in_the_offered_list():
    def proposal(status, thread="123"):
        return Proposal(
            id=f"p-{status}",
            name="expenses",
            purpose="`add` also takes a category",
            kind=ProposalKind.CHANGE,
            change=CHANGE_TEXT,
            channel="telegram",
            thread=thread,
            status=status,
            created="2026-11-03T10:00:00+08:00",
        )

    here = ("telegram", "123")
    lines = {s: render_proposals([proposal(s)], {"expenses"}, here) for s in ProposalStatus}
    assert lines[ProposalStatus.PROPOSED] == (
        "- a change to expenses: `add` also takes a category (offered 2026-11-03, waiting for his Change it: do not "
        "offer it again, the card is there)"
    )
    assert lines[ProposalStatus.DONE] == "(none)"  # made: the module under Modules has it
    assert "runs as it was: call `change_module` again only if he asks" in lines[ProposalStatus.FAILED]
    assert "he chose Not now" in lines[ProposalStatus.DECLINED]
    elsewhere = render_proposals([proposal(ProposalStatus.PROPOSED, thread="9")], {"expenses"}, here)
    assert "in another chat: if he asks here, call `change_module` here" in elsewhere


# ---- the tool ----------------------------------------------------------------------------------------


def test_the_change_reads_as_lines_and_goes_to_the_builder_with_why_first():
    args = ChangeArgs.model_validate({**CATEGORY, "module": "Expenses", "change": "- one\n- two\n"})
    assert args.module == "expenses" and args.change == ["one", "two"]
    assert ChangeArgs.model_validate(CATEGORY).text() == CHANGE_TEXT


async def test_a_change_ends_in_a_card_and_is_stored(chg):
    card = await offer(chg)
    assert card["choices"] == [CHANGE_IT, NOT_NOW]
    assert card["text"] == (
        "I can change it for that.\n\nA change to expenses (now v0.1.0):\n"
        "- `add` also takes a category: add {amount: number, description: string, category: optional string}\n"
        "- `summary` gives totals per category\n"
        "It keeps its data, and runs as it is until the new version passes its tests. Nothing changes until you choose."
    )
    p = await ProposalStore(chg.kv).get(card["ref"])
    assert (p.kind, p.name, p.change, p.base_version, p.spec) == (
        ProposalKind.CHANGE, "expenses", CHANGE_TEXT, "0.1.0", "",
    )  # fmt: skip
    assert p.purpose.startswith("`add` also takes a category")
    assert chg.bus.events("trace.plan")[-1][1]["proposal"] == "expenses"
    assert not chg.builder.started  # nothing is built until he taps


@pytest.mark.parametrize(
    "module, error",
    [
        ("hello", "hello is hand-written, not grown: only modules marked grown can be changed. Tell Hansen."),
        ("groceries", "there is no module 'groceries' to change (grown: expenses). If Hansen wants a new one"),
    ],
)
async def test_only_a_grown_module_can_be_changed(chg, module, error):
    chg.llm_script = [call("change_module", {**CATEGORY, "module": module}), say("I can't change that one.")]
    await chg.send("sense.chat", chat("make it count words too").data)
    (outcome,) = chg.bus.events("trace.plan")[-1][1]["tools"]
    assert outcome["result"]["ok"] is False and outcome["result"]["error"].startswith(error)
    assert not chg.bus.events("out.ask") and chg.bus.events("out.say")[-1][1]["text"] == "I can't change that one."


async def test_a_module_being_built_cannot_be_changed_until_it_is_done(chg):
    chg.builder.records["b0"] = {"id": "b0", "name": "expenses", "status": "building"}
    chg.llm_script = [call("change_module", CATEGORY), say("It's being built right now.")]
    await chg.send("sense.chat", chat("add a category").data)
    (outcome,) = chg.bus.events("trace.plan")[-1][1]["tools"]
    assert "is being built or changed right now" in outcome["result"]["error"]


async def test_proposing_a_module_that_exists_points_to_changing_it(chg):
    chg.llm_script = [call("propose_module", EXPENSES), say("ok")]
    await chg.send("sense.chat", chat("I want to track my expenses").data)
    (outcome,) = chg.bus.events("trace.plan")[-1][1]["tools"]
    assert "if it should do more or work differently, call `change_module` for it" in outcome["result"]["error"]
    assert ProposeArgs  # the same tool, refused: no card


# ---- the tap -----------------------------------------------------------------------------------------


async def test_change_it_starts_a_change_build(chg):
    ref = await changing(chg)
    (started,) = chg.builder.started
    assert started["name"] == "expenses" and started["change"] == CHANGE_TEXT and started["spec"] == ""
    assert (started["channel"], started["thread"]) == ("telegram", "123")
    assert chg.bus.events("out.say")[-1][1]["text"] == (
        "Changing expenses. It runs as it is until the new version is ready; I'll tell you here."
    )
    assert (await ProposalStore(chg.kv).get(ref)).status == ProposalStatus.BUILDING


async def test_not_now_leaves_the_module_as_it_is(chg):
    card = await offer(chg)
    await chg.send("sense.feedback", tap(card["ref"], NOT_NOW))
    assert not chg.builder.started
    assert chg.bus.events("out.say")[-1][1]["text"].startswith("OK, I'll leave expenses as it is.")
    await chg.send("sense.feedback", tap(card["ref"], CHANGE_IT))  # an old card
    assert chg.bus.events("out.say")[-1][1]["text"].startswith("You chose to leave expenses as it is.")


async def test_a_refused_change_comes_back_as_a_fresh_change_card(chg):
    chg.builder.refuse = "the builder is busy: 5 builds are waiting; try again later"
    card = await offer(chg)
    await chg.send("sense.feedback", tap(card["ref"], CHANGE_IT))
    again = chg.bus.events("out.ask")[-1][1]
    assert again["text"].startswith("The builder won't change expenses: the builder is busy")
    assert again["choices"] == [CHANGE_IT, NOT_NOW]


# ---- the result --------------------------------------------------------------------------------------


async def test_a_change_done_says_the_data_is_kept(chg):
    ref = await changing(chg)
    await chg.send("build.done", build_event(version="0.2.0", mode="change"))
    assert chg.bus.events("out.say")[-1][1]["text"] == (
        "expenses is changed and running (version 0.2.0), with its data kept. Ask me about it any time."
    )
    assert (await ProposalStore(chg.kv).get(ref)).status == ProposalStatus.DONE


@pytest.mark.parametrize(
    "stage, still_runs",
    [("tests", True), ("snapshot", True), ("promote", True), ("deploy", False)],
)
async def test_a_change_that_failed_says_whether_the_old_version_still_runs(chg, stage, still_runs):
    await changing(chg)
    await chg.send("build.failed", build_event(stage=stage, error="2 tests failed after 6 rounds", mode="change"))
    text = chg.bus.events("out.say")[-1][1]["text"]
    assert text.startswith(f"Changing expenses failed at {stage}: 2 tests failed after 6 rounds")
    assert ("expenses still runs as it was (version 0.1.0)." in text) is still_runs
