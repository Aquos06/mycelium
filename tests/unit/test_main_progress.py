"""A build Main started, followed in the thread that asked: build.stage -> one out.progress per build, changed in
place (same ref, higher seq); build.done / build.failed -> the say, then its last state. Rendered from the event
alone: each carries every finished round in a line."""

import asyncio
from zoneinfo import ZoneInfo

import pytest

from main.progress import as_text, duration, ended, running
from main.proposals import ProposalStore
from main.service import MainService
from main.thread import ThreadStore
from mycelium_sdk import InMemoryBus, InMemoryKV
from mycelium_sdk.build import BuildDone, BuildFailed, BuildRecord, BuildStage, Round
from tests.unit.test_main import TODAY, World
from tests.unit.test_main_grow import Builder, build_event, built

TAIPEI = ZoneInfo("Asia/Taipei")
SINCE = "2026-11-07T06:05:00+00:00"
FAILED_ROUND = {
    "n": 1,
    "stage": "tests",
    "passed": False,
    "summary": "tests failed: 1 failed, 5 passed; test_add_keeps_the_day: KeyError: 'day'",
    "seconds": 190.0,
}
PASSED_ROUND = {"n": 2, "stage": "tests", "passed": True, "summary": "the tests pass (6 passed)", "seconds": 75.0}


@pytest.fixture
async def grow():
    """Main with a builder, and no module yet: the one being grown (as in test_main_grow)."""
    bus = InMemoryBus()
    w = World(bus, [])
    w.modules = [{"name": "hello", "status": "running", "manifest": {"purpose": "Counts chat messages."}}]
    await w.start()
    w.builder = Builder(bus)
    await w.builder.start()
    w.kv = InMemoryKV()
    w.svc = MainService(bus, ThreadStore(w.kv, max_turns=10), today=lambda: TODAY, build_timeout=0.2)
    await w.svc.start()
    return w


def at(stage_, n, history=(), mode="new", **extra) -> dict:
    """A build.stage event's own fields (build_event adds the id, the name and the thread)."""
    return {
        "mode": mode,
        "stage": stage_,
        "round": n,
        "max_rounds": 6,
        "since": SINCE,
        "history": list(history),
        **extra,
    }


def stage(*args, **kwargs) -> BuildStage:
    return BuildStage.model_validate(build_event(**at(*args, **kwargs), seq=1))


def done(history=(), **extra) -> BuildDone:
    return BuildDone.model_validate(build_event(**{"version": "0.1.0", "history": list(history), **extra}))


def failed(stage_, error, history=(), **extra) -> BuildFailed:
    return BuildFailed.model_validate(build_event(stage=stage_, error=error, history=list(history), **extra))


def lines(card):
    title, steps = card
    return title, [(s.state.value, s.text) for s in steps]


# ---- the steps ----------------------------------------------------------------------------------------


def test_a_new_build_writing_its_first_round():
    assert lines(running(stage("coder", 1))) == (
        "Building expenses",
        [("active", "Round 1 of 6: writing the module"), ("pending", "Save it"), ("pending", "Start it")],
    )


def test_a_failed_round_stays_in_view_while_the_next_one_fixes_it():
    title, steps = lines(running(stage("verify", 2, [FAILED_ROUND])))
    assert steps[0] == ("failed", f"Round 1: {FAILED_ROUND['summary']} · 3 min")
    assert steps[1] == ("active", "Round 2 of 6: building it and running its tests")
    assert lines(running(stage("coder", 2, [FAILED_ROUND])))[1][1] == ("active", "Round 2 of 6: fixing what failed")
    assert lines(running(stage("checks", 1)))[1][0] == ("active", "Round 1 of 6: checking the files")


def test_a_change_copies_its_data_before_it_is_saved():
    ev = stage("promote", 1, [PASSED_ROUND | {"n": 1}], mode="change", base_version="0.1.0")
    assert lines(running(ev)) == (
        "Changing expenses (now v0.1.0)",
        [
            ("done", "Round 1: the tests pass (6 passed) · 1 min"),
            ("done", "Copy its data"),
            ("active", "Save the new version"),
            ("pending", "Start the new version"),
        ],
    )
    assert lines(running(stage("coder", 1, mode="change")))[1][0] == ("active", "Round 1 of 6: writing the change")


def test_done_ticks_every_step():
    title, steps = lines(ended(done([FAILED_ROUND, PASSED_ROUND])))
    assert title == "Built expenses v0.1.0"
    assert [s for s, _ in steps] == ["failed", "done", "done", "done"]
    change = done(mode="change", base_version="0.1.0", version="0.2.0")
    assert lines(ended(change))[0] == "Changed expenses: v0.1.0 → v0.2.0"


@pytest.mark.parametrize(
    "ev, last",
    [
        # every round failed: the rounds say why, nothing more to add
        (
            ("tests", "no working module after 6 rounds", [FAILED_ROUND]),
            [
                ("failed", f"Round 1: {FAILED_ROUND['summary']} · 3 min"),
                ("pending", "Save it"),
                ("pending", "Start it"),
            ],
        ),
        # stopped inside a round: the reason is a step of its own
        (
            ("coder", "the build took longer than 3600s", [FAILED_ROUND]),
            [
                ("failed", f"Round 1: {FAILED_ROUND['summary']} · 3 min"),
                ("failed", "Stopped: the build took longer than 3600s"),
                ("pending", "Save it"),
                ("pending", "Start it"),
            ],
        ),
        # after the rounds: the step it stopped at
        (
            ("deploy", "rpc.sys.deploy: port in use", [PASSED_ROUND]),
            [
                ("done", "Round 2: the tests pass (6 passed) · 1 min"),
                ("done", "Save it"),
                ("failed", "Start it: rpc.sys.deploy: port in use"),
            ],
        ),
    ],
)
def test_failed_says_where_it_stopped(ev, last):
    title, steps = lines(ended(failed(*ev)))
    assert title == "Building expenses failed" and steps == last


def test_a_build_record_ends_the_way_its_event_did():
    record = BuildRecord(
        name="expenses",
        spec="# Spec: expenses\n",
        coder="fake",
        status="failed",
        stage="verify",
        error="image build failed",
        rounds=[Round.model_validate(FAILED_ROUND)],
        started="2026-11-07T06:00:00+00:00",
        finished="2026-11-07T06:03:10+00:00",
    )
    ev = record.ended()
    assert isinstance(ev, BuildFailed) and ev.seconds == 190.0 and ev.history[0].summary == FAILED_ROUND["summary"]
    assert lines(ended(ev))[1][0] == ("failed", f"Round 1: {FAILED_ROUND['summary']} · 3 min")
    assert record.model_copy(update={"status": "building"}).ended() is None
    assert isinstance(record.model_copy(update={"status": "done", "version": "0.1.0"}).ended(), BuildDone)


def test_the_text_for_a_channel_without_cards():
    title, steps = running(stage("coder", 2, [FAILED_ROUND]))
    assert as_text(title, steps, TAIPEI).splitlines() == [
        "Building expenses",
        f"❌ Round 1: {FAILED_ROUND['summary']} · 3 min",
        "⏳ Round 2 of 6: fixing what failed (since 14:05)",
        "▫️ Save it",
        "▫️ Start it",
    ]


@pytest.mark.parametrize(
    "seconds, said",
    [
        (42, "42 s"),
        (59.6, "1 min"),
        (150, "3 min"),  # half up, as the web app rounds (Python's round() would say 2)
        (190, "3 min"),
        (3570, "1 h"),  # not "60 min"
        (3900, "1 h 5 min"),
        (7170, "2 h"),  # not "1 h 60 min"
    ],
)
def test_durations_round_half_up_and_carry_into_hours(seconds, said):
    assert duration(seconds) == said


# ---- on the bus ---------------------------------------------------------------------------------------


async def test_each_step_updates_one_progress_message_in_the_thread_that_asked(grow):
    await built(grow)
    await grow.send("build.stage", build_event(**at("coder", 1), seq=1))
    await grow.send("build.stage", build_event(**at("verify", 1), seq=3))
    cards = [d for _, d in grow.bus.events("out.progress")]
    assert [(c["ref"], c["seq"], c["state"]) for c in cards] == [("b1", 1, "running"), ("b1", 3, "running")]
    assert (cards[-1]["channel"], cards[-1]["thread"]) == ("telegram", "123")
    assert cards[-1]["steps"][0] == {
        "text": "Round 1 of 6: building it and running its tests",
        "state": "active",
        "since": SINCE,
    }
    assert cards[-1]["text"].startswith("Building expenses\n⏳ Round 1 of 6: building it")
    assert cards[-1]["cause"] == grow.bus.events("build.stage")[-1][1]["id"]
    # the thread's history is the conversation: a progress message is not a turn
    assert all("Round 1" not in t.text for t in (await grow.svc.store.load("telegram", "123")).turns)


async def test_a_build_nobody_asked_for_in_a_thread_has_no_progress_message(grow):
    await grow.send("build.stage", build_event(build_id="mctl-1", channel=None, thread=None, **at("coder", 1), seq=1))
    assert not grow.bus.events("out.progress")


async def test_an_event_that_does_not_read_is_left_alone(grow):
    await built(grow)
    await grow.send("build.stage", build_event(**at("somewhere", 1), seq=1))
    await grow.send("build.done", build_event())  # no version
    assert not grow.bus.events("out.progress")


async def test_a_step_waits_for_the_reply_to_the_tap_that_started_it(grow):
    await built(grow)
    lock = grow.svc._lock("telegram", "123")
    await lock.acquire()  # the tap's turn, still saying "Building expenses"
    await grow.bus.publish("build.stage", build_event(**at("coder", 1), seq=1))
    await asyncio.sleep(0.01)
    assert not grow.bus.events("out.progress")
    lock.release()
    await grow.svc.drain()
    assert len(grow.bus.events("out.progress")) == 1


async def test_the_reply_comes_first_then_the_progress_message_ends(grow):
    await built(grow)
    await grow.send("build.done", build_event(version="0.1.0", seq=9, history=[PASSED_ROUND]))
    subjects = [s for s, _ in grow.bus.events("out.>")]
    assert subjects[-2:] == ["out.say", "out.progress"]
    card = grow.bus.events("out.progress")[-1][1]
    assert (card["state"], card["title"], card["seq"]) == ("done", "Built expenses v0.1.0", 9)


async def test_a_progress_message_that_cannot_go_out_does_not_stop_the_reply(grow):
    ref = await built(grow)
    publish = grow.bus.publish

    async def no_cards(subject, data):
        if subject == "out.progress":
            raise ConnectionError("bus hiccup")
        await publish(subject, data)

    grow.bus.publish = no_cards
    await grow.send("build.done", build_event(version="0.1.0", seq=9))
    assert grow.bus.events("out.say")[-1][1]["text"].startswith("expenses is built and running")
    assert (await ProposalStore(grow.kv).get(ref)).status == "done"


async def test_a_build_whose_proposal_is_not_building_still_ends_its_progress_message(grow):
    """Its start went unanswered and the card was declined, or Main never stored it: the card was shown all the
    same (build.stage needs only the thread), so it must not spin forever."""
    says = len(grow.bus.events("out.say"))
    await grow.send("build.stage", build_event(build_id="b9", **at("coder", 1), seq=1))
    await grow.send("build.failed", build_event(build_id="b9", stage="tests", error="1 failed", seq=5))
    card = grow.bus.events("out.progress")[-1][1]
    assert (card["ref"], card["state"]) == ("b9", "failed")
    assert len(grow.bus.events("out.say")) == says  # nothing to tell: no proposal of this thread started it


async def test_a_build_that_ended_while_main_was_down_closes_its_progress_message_too(grow):
    ref = await built(grow)
    grow.builder.records["b1"].update(
        status="failed",
        stage="verify",
        error="image build failed",
        rounds=[FAILED_ROUND | {"stage": "build"}],
    )
    again = MainService(grow.bus, ThreadStore(grow.kv), today=lambda: TODAY)
    await again.catch_up()
    card = grow.bus.events("out.progress")[-1][1]
    assert (card["ref"], card["state"], card["title"]) == ("b1", "failed", "Building expenses failed")
    assert card["steps"][-1]["text"] == "Start it" and card["cause"] is None
    assert (await ProposalStore(grow.kv).get(ref)).status == "failed"


async def test_a_build_the_builder_lost_closes_its_progress_message(grow):
    await built(grow)
    del grow.builder.records["b1"]
    await grow.svc.catch_up(attempts=1)
    card = grow.bus.events("out.progress")[-1][1]
    assert (card["ref"], card["state"]) == ("b1", "failed")
    assert [s["text"] for s in card["steps"]] == ["Stopped: the builder has no record of it", "Save it", "Start it"]
