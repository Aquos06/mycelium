"""Main deletes a module the builder grew, only on Hansen's tap: delete_module -> a deletion stored -> its card
(Delete it / Keep it) -> a tap -> rpc.build.remove while the tap waits -> where the data and the code went, in the
thread that asked. A hand-written module, or one being built, is refused."""

import asyncio

import pytest

from main.prompt import render_proposals
from main.proposals import Proposal, ProposalKind, ProposalStatus, ProposalStore
from main.service import BUILD_IT, DELETE_IT, KEEP_IT, MainService, _deleted
from main.thread import ThreadStore
from main.tools import DeleteArgs
from mycelium_sdk import InMemoryBus, InMemoryKV, Message
from mycelium_sdk.build import Removed
from tests.unit.test_main import TODAY, World, call, chat, say
from tests.unit.test_main_change import GROWN, HELLO
from tests.unit.test_main_grow import Builder, build_event, tap

COPY = "mycelium-data-expenses-v0.1.0-removed-20261108T020000Z"


class Remover(Builder):
    """The builder, with rpc.build.remove as it answers it."""

    def __init__(self, bus: InMemoryBus):
        super().__init__(bus)
        self.removed: list[str] = []
        self.remove_refuse: str | None = None
        self.remove_down = False  # no answer in time
        self.remove_gate: asyncio.Event | None = None  # set it to hold a deletion until the test lets it go
        self.waiting = False  # a deletion is held at the gate

    async def start(self):
        await super().start()
        await self.bus.subscribe("rpc.build.remove", self._remove)

    async def _remove(self, msg: Message):
        if self.remove_down:
            return
        if self.remove_refuse:
            await msg.respond({"ok": False, "error": self.remove_refuse})
            return
        name = msg.data["name"]
        if self.remove_gate is not None:
            self.waiting = True
            await self.remove_gate.wait()
        self.removed.append(name)
        await self.bus.publish("sys.module.removed", {"name": name, "data": COPY})  # the supervisor's, before the reply
        reply = {"name": name, "version": "0.1.0", "data": COPY, "commit": "a1b2c3d4e5f6", "tag": f"{name}-v0.1.0"}
        await msg.respond({"ok": True, **reply})


@pytest.fixture
async def dele():
    bus = InMemoryBus()
    w = World(bus, [])
    w.modules = [HELLO, GROWN]
    w.grown = ["expenses"]
    w.folders = ["expenses", "hello"]
    await w.start()
    w.builder = Remover(bus)
    await w.builder.start()
    w.kv = InMemoryKV()
    w.svc = MainService(bus, ThreadStore(w.kv, max_turns=10), today=lambda: TODAY, delete_timeout=0.2)
    await w.svc.start()
    return w


async def ask_to_delete(w, module="expenses") -> dict:
    """One turn that ends in a deletion card; returns it (out.ask)."""
    w.llm_script = [call("delete_module", {"module": module}, text="I can delete it.")]
    await w.send("sense.chat", chat(f"delete {module}, I don't use it").data)
    asks = w.bus.events("out.ask")
    assert asks, "a deletion should end in a card"
    return asks[-1][1]


def last_say(w) -> str:
    return w.bus.events("out.say")[-1][1]["text"]


def says(w) -> list[str]:
    return [e[1]["text"] for e in w.bus.events("out.say")]


async def until(done, timeout: float = 2.0) -> None:
    """For a test that cannot drain: a deletion held at the gate keeps Main's tasks running."""
    for _ in range(int(timeout / 0.01)):
        if done():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("it never happened")


# ---- what the planner sees ---------------------------------------------------------------------------


async def test_the_policy_says_when_to_delete_and_when_it_is_a_change(dele):
    dele.llm_script = [say("ok")]
    await dele.send("sense.chat", chat("hi").data)
    system = dele.llm_requests[0]["system"]
    assert "Use `delete_module` when Hansen wants a whole module marked grown gone" in system
    assert "never because you think one is unused" in system
    assert "Taking an entry out of a module is `change_module`, not this" in system


def test_deletion_lines_in_the_offered_list():
    def proposal(status, thread="123"):
        return Proposal(
            id=f"p-{status}",
            name="expenses",
            purpose="",
            kind=ProposalKind.DELETE,
            channel="telegram",
            thread=thread,
            status=status,
            created="2026-11-03T10:00:00+08:00",
            note="'expenses' is being built (b3)",
        )

    here = ("telegram", "123")
    lines = {s: render_proposals([proposal(s)], {"expenses"}, here) for s in ProposalStatus}
    assert lines[ProposalStatus.PROPOSED] == (
        "- deleting expenses (asked 2026-11-03, waiting for his Delete it: do not ask again, the card is there)"
    )
    assert lines[ProposalStatus.DONE] == "(none)"  # gone: neither under Modules nor offered
    assert "he chose Keep it on 2026-11-03" in lines[ProposalStatus.DECLINED]
    assert "did not go through on 2026-11-03 ('expenses' is being built (b3))" in lines[ProposalStatus.FAILED]
    elsewhere = render_proposals([proposal(ProposalStatus.PROPOSED, thread="9")], {"expenses"}, here)
    assert "in another chat: if he asks here, call `delete_module` here" in elsewhere


# ---- the tool ----------------------------------------------------------------------------------------


def test_the_module_reads_as_a_slug():
    assert DeleteArgs.model_validate({"module": " Water Log "}).module == "water-log"


async def test_a_deletion_ends_in_a_card_and_is_stored(dele):
    card = await ask_to_delete(dele)
    assert card["choices"] == [DELETE_IT, KEEP_IT]
    assert card["text"].startswith("I can delete it.\n\nDelete expenses (v0.1.0)?\nIt stops for good")
    assert "Its data is copied aside first and its code stays in git" in card["text"]
    p = await ProposalStore(dele.kv).get(card["ref"])
    assert (p.kind, p.name, p.base_version, p.status) == (
        ProposalKind.DELETE,
        "expenses",
        "0.1.0",
        ProposalStatus.PROPOSED,
    )
    assert dele.bus.events("trace.plan")[-1][1]["proposal"] == "expenses"
    assert not dele.builder.removed  # nothing is deleted before the tap


@pytest.mark.parametrize(
    ("module", "error"),
    [
        ("hello", "hello is hand-written, not grown: only modules marked grown can be deleted. Tell Hansen."),
        ("groceries", "there is no module 'groceries' to delete (grown: expenses)."),
    ],
)
async def test_only_a_grown_module_can_be_deleted(dele, module, error):
    dele.llm_script = [call("delete_module", {"module": module}), say("I can't delete that one.")]
    await dele.send("sense.chat", chat(f"delete {module}").data)
    (outcome,) = dele.bus.events("trace.plan")[-1][1]["tools"]
    assert outcome["result"] == {"ok": False, "error": error}
    assert not dele.bus.events("out.ask") and last_say(dele) == "I can't delete that one."


async def test_a_module_still_listed_whose_folder_is_gone_can_be_deleted(dele):
    dele.modules.append({"name": "ghost", "status": "retired", "version": "0.1.0", "manifest": {}})
    card = await ask_to_delete(dele, "ghost")
    assert card["text"].endswith("Nothing is deleted until you choose.")


async def test_a_module_being_built_cannot_be_deleted_until_it_is_done(dele):
    dele.builder.records["b0"] = {"id": "b0", "name": "expenses", "status": "building"}
    dele.llm_script = [call("delete_module", {"module": "expenses"}), say("It's being built right now.")]
    await dele.send("sense.chat", chat("delete expenses").data)
    (outcome,) = dele.bus.events("trace.plan")[-1][1]["tools"]
    assert "is being built or changed right now" in outcome["result"]["error"]


# ---- the tap -----------------------------------------------------------------------------------------


async def test_delete_it_deletes_and_says_where_the_data_and_the_code_went(dele):
    card = await ask_to_delete(dele)
    await dele.send("sense.feedback", tap(card["ref"], DELETE_IT))
    assert dele.builder.removed == ["expenses"]
    assert last_say(dele) == (
        f"Deleted expenses. I kept its data in {COPY} and its code in git as expenses-v0.1.0, in case you want it back."
    )
    p = await ProposalStore(dele.kv).get(card["ref"])
    assert p.status == ProposalStatus.DONE and p.decided
    thread = await ThreadStore(dele.kv).load("telegram", "123")
    assert [t.text for t in thread.turns[-2:]] == [DELETE_IT, last_say(dele)]

    await dele.send("sense.feedback", tap(card["ref"], DELETE_IT))  # a second tap
    assert dele.builder.removed == ["expenses"] and last_say(dele) == "expenses is already deleted."


async def test_keep_it_keeps_the_module(dele):
    card = await ask_to_delete(dele)
    await dele.send("sense.feedback", tap(card["ref"], KEEP_IT))
    assert not dele.builder.removed
    assert last_say(dele) == "OK, I'll keep expenses. Ask me again whenever you want it gone."
    await dele.send("sense.feedback", tap(card["ref"], DELETE_IT))  # an old card
    assert not dele.builder.removed and last_say(dele).startswith("You chose to keep expenses.")


async def test_another_cards_yes_never_deletes(dele):
    card = await ask_to_delete(dele)
    says = len(dele.bus.events("out.say"))
    await dele.send("sense.feedback", tap(card["ref"], BUILD_IT))
    assert not dele.builder.removed and not dele.builder.started and len(dele.bus.events("out.say")) == says
    assert (await ProposalStore(dele.kv).get(card["ref"])).status == ProposalStatus.PROPOSED


def test_a_module_with_nothing_kept_is_only_said_deleted():
    assert _deleted(Removed(name="ghost")) == "Deleted ghost."
    assert _deleted(Removed(name="ghost", data="d")) == "Deleted ghost. I kept its data in d, in case you want it back."


async def test_a_refused_deletion_is_told_and_not_offered_again(dele):
    dele.builder.remove_refuse = "'expenses' is being built (b3); delete it once that build has ended"
    card = await ask_to_delete(dele)
    asks = len(dele.bus.events("out.ask"))
    await dele.send("sense.feedback", tap(card["ref"], DELETE_IT))
    assert last_say(dele) == (
        "I couldn't delete expenses: 'expenses' is being built (b3); delete it once that build has ended"
    )
    assert len(dele.bus.events("out.ask")) == asks  # a second tap would not undo what stopped it
    p = await ProposalStore(dele.kv).get(card["ref"])
    assert p.status == ProposalStatus.FAILED and "being built" in p.note


async def test_no_answer_in_time_but_gone_is_deleted(dele):
    dele.builder.remove_down = True
    card = await ask_to_delete(dele)
    dele.modules, dele.folders = [HELLO], ["hello"]  # it went through; the answer was late
    await dele.send("sense.feedback", tap(card["ref"], DELETE_IT))
    assert last_say(dele) == (
        "Deleted expenses. The builder answered late, so I can't say what it kept: any data and code it had are under "
        "names ending in -removed-<time> (a Docker volume, a git tag)."
    )
    assert (await ProposalStore(dele.kv).get(card["ref"])).status == ProposalStatus.DONE


async def test_no_answer_in_time_and_still_there_says_so(dele):
    dele.builder.remove_down = True
    card = await ask_to_delete(dele)
    await dele.send("sense.feedback", tap(card["ref"], DELETE_IT))
    assert last_say(dele) == (
        "The builder didn't answer in time, so expenses may be deleted only partly. Ask me again to finish."
    )
    assert (await ProposalStore(dele.kv).get(card["ref"])).status == ProposalStatus.FAILED


async def test_a_build_whose_start_went_unanswered_is_never_taken_for_a_deletion(dele):
    card = await ask_to_delete(dele)  # the latest proposal of the name, in this thread, waiting
    await dele.send("build.done", build_event(version="0.2.0", mode="change"))
    p = await ProposalStore(dele.kv).get(card["ref"])
    assert p.status == ProposalStatus.PROPOSED and p.build_id is None


async def test_the_chat_goes_on_while_a_module_is_being_deleted(dele):
    dele.svc.delete_timeout = 5.0
    dele.builder.remove_gate = asyncio.Event()
    card = await ask_to_delete(dele)
    dele.llm_script = [say("Hi there.")]
    await dele.bus.publish("sense.feedback", tap(card["ref"], DELETE_IT))
    await until(lambda: dele.builder.waiting)  # the supervisor is copying its data

    await dele.bus.publish("sense.chat", chat("hi").data)
    await until(lambda: "Hi there." in says(dele))  # answered meanwhile, not after the deletion
    await dele.bus.publish("sense.feedback", tap(card["ref"], DELETE_IT))  # a second tap
    await until(lambda: "expenses is being deleted now. I'll tell you here when it's done." in says(dele))

    dele.builder.remove_gate.set()
    await dele.svc.drain()
    assert dele.builder.removed == ["expenses"] and last_say(dele).startswith("Deleted expenses. I kept its data")
    assert (await ProposalStore(dele.kv).get(card["ref"])).status == ProposalStatus.DONE


async def test_a_card_left_after_a_deletion_from_elsewhere_never_deletes(dele):
    card = await ask_to_delete(dele)
    await dele.send("sys.module.removed", {"name": "expenses", "data": COPY})  # deleted from its page
    p = await ProposalStore(dele.kv).get(card["ref"])
    assert (p.status, p.note) == (ProposalStatus.DONE, "deleted elsewhere")

    await dele.send("sense.feedback", tap(card["ref"], DELETE_IT))  # weeks later, with a new expenses grown
    assert not dele.builder.removed and last_say(dele) == "expenses is already deleted."


async def test_a_module_deleted_here_is_not_said_to_have_stopped_running(dele):
    card = await ask_to_delete(dele)
    await dele.send("sense.feedback", tap(card["ref"], DELETE_IT))
    dele.modules = [HELLO]
    dele.llm_script = [say("Hi.")]
    await dele.send("sense.chat", chat("hi").data)
    assert "stopped running" not in dele.llm_requests[-1]["messages"][-1]["content"]
