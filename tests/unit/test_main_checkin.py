"""Check-ins: at set times of day Main looks at the day (memory, the modules, read only, and the reminders) in one model
turn and writes Hansen a message, or stays quiet. The wake policy decides in code first (voted down, told already
today, quiet hours, a chat in progress, the budget), so most check-ins that would be noise never reach the model."""

import asyncio
from datetime import UTC, datetime, time, timedelta

import pytest

from main.prompt import checkin_prompt
from main.service import CHOOSE, MainService
from main.settings import MainSettings, checkin_times
from main.thread import ThreadStore
from main.tools import may_write
from main.wake import CHECKIN, Verdict, WakePolicy
from mycelium_sdk import Envelope, InMemoryBus, InMemoryKV, RequestSpec
from tests.unit.test_main import World, call, say
from tests.unit.test_main_wake import T0, TPE, Clock, traces, unasked, write

EVE = T0.replace(hour=21)  # Wed 2026-11-11 21:00
NOTHING_TODAY = "Nothing in expenses today: anything to log?"


@pytest.fixture
async def w():
    bus = InMemoryBus()
    w = World(bus, [])
    await w.start()
    w.clock = Clock(T0)
    w.svc = MainService(
        bus,
        ThreadStore(InMemoryKV(), max_turns=20),
        today=lambda: w.clock.now.date(),
        wake=WakePolicy(every_s=0, notice_delay_s=0, checkins=()),  # the tests call check_in themselves
        clock=w.clock,
    )
    await w.svc.start()
    await write(w)  # 11:00: the thread a check-in goes to
    w.clock.now = EVE
    return w


def plans(w) -> list[dict]:
    return [d for _, d in w.bus.events("trace.plan") if d.get("checkin")]


async def test_a_check_in_looks_then_writes_one_message_in_the_home_thread(w):
    w.llm_script = [call("ask_module", {"module": "expenses", "action": "summary"}), say(NOTHING_TODAY)]
    await w.svc.check_in(time(21))

    (out,) = unasked(w)
    assert (out["text"], out["channel"], out["thread"]) == (NOTHING_TODAY, "telegram", "123")
    (wake,) = traces(w)
    assert wake["reason"] == "checkin" and wake["items"][0]["verdict"] == Verdict.SENT
    assert wake["items"][0]["reply_id"] == out["id"] and wake["sent_today"] == 1
    (plan,) = plans(w)
    assert plan["checkin"] == "21:00" and plan["reply_id"] == out["id"] and plan["output"]["say"] == NOTHING_TODAY
    assert [t["name"] for t in plan["tools"]] == ["ask_module"]
    request = w.llm_requests[-1]
    assert {t["name"] for t in request["tools"]} == {"recall", "ask_module", "show", "stay_quiet"}
    assert "Nobody wrote to you: it is check-in time, Wednesday 2026-11-11 at 21:00" in request["system"]
    assert "the evening check-in" in request["system"]
    await w.svc.drain()
    kept = (await w.svc.store.load("telegram", "123")).turns[-1]
    assert (kept.text, kept.unasked) == (NOTHING_TODAY, True)  # a reply to it is read with it


async def test_staying_quiet_sends_nothing_and_spends_no_budget(w):
    w.llm_script = [call("stay_quiet", {"why": "expenses has today's lunch; nothing is open"})]
    await w.svc.check_in(time(21))

    assert unasked(w) == []
    (wake,) = traces(w)
    item = wake["items"][0]
    assert (item["verdict"], item["text"]) == (Verdict.NOTHING, "expenses has today's lunch; nothing is open")
    assert wake["sent_today"] == 0 and plans(w)[0]["output"]["say"] == ""
    assert (await w.svc.wakes.load()).sent == 0


async def test_staying_quiet_wins_over_words_beside_it(w):
    w.llm_script = [call("stay_quiet", {"why": "nothing new"}, text="Good evening!")]
    await w.svc.check_in(time(21))
    assert unasked(w) == [] and traces(w)[0]["items"][0]["verdict"] == Verdict.NOTHING


async def test_a_check_in_sees_and_calls_only_requests_that_read(w):
    w.modules[0]["manifest"]["requests"] = ["summary", "add", "delete", "logwater"]
    w.llm_script = [
        call("ask_module", {"module": "expenses", "action": "delete", "args": {"id": 1}}),
        call("stay_quiet", {"why": "x"}, id="t2"),
    ]
    await w.svc.check_in(time(21))
    deleted = plans(w)[0]["tools"][0]["result"]
    assert deleted == {"ok": False, "error": "expenses has no request 'delete'; its requests: summary"}
    system = w.llm_requests[-2]["system"]
    assert "expenses.summary" in system and "expenses.add" not in system and "expenses.logwater" not in system


@pytest.mark.parametrize(
    ("action", "spec", "writes"),
    [
        ("summary", None, False),
        ("delete", None, True),  # the SDK's verbs, not only Main's old few
        ("addexpense", None, True),  # a write verb run into a word
        ("settings", None, True),  # a read named like a write is given up
        ("settings", RequestSpec(description="The module's settings.", writes=False), False),  # declared: a read
        ("summary", RequestSpec(description="Totals, and resets the count.", writes=True), True),  # declared
    ],
)
def test_what_a_check_in_counts_as_a_write(action, spec, writes):
    assert may_write(action, spec) is writes


async def test_any_stay_quiet_call_is_quiet_even_one_that_does_not_read(w):
    w.llm_script = [call("stay_quiet", {"why": "x" * 400}), say("Okay, nothing to report tonight.")]
    await w.svc.check_in(time(21))
    assert unasked(w) == []
    assert traces(w)[0]["items"][0]["text"] == "it chose to stay quiet"


async def test_what_it_shows_goes_with_its_message(w):
    w.llm_script = [
        call("ask_module", {"module": "expenses", "action": "summary"}),
        call("show", {"source": "expenses.summary", "kind": "stats", "fields": ["total_twd"]}, id="t2"),
        say("October's spending is in: NT$4,210."),
    ]
    await w.svc.check_in(time(21))
    (out,) = unasked(w)
    assert [b["kind"] for b in out["blocks"]] == ["stats"]


@pytest.mark.parametrize(
    ("script", "why"),
    [
        ([say(""), say("")], "it wrote nothing"),  # asked once more for a choice: empty again
        ([say("I've saved that for you.")], "its message said something was saved or set"),
        ([{"ok": False, "error": "budget exceeded"}], "the model did not answer"),
        ([call("recall", {"query": "a"}), call("recall", {"query": "b"}, id="t2")], "no message after 2 rounds"),
    ],
)
async def test_a_check_in_that_comes_to_no_message_stays_quiet(w, script, why):
    w.svc.max_rounds = 2
    w.llm_script = script
    await w.svc.check_in(time(21))
    assert unasked(w) == []
    item = traces(w)[0]["items"][0]
    assert (item["verdict"], item["text"]) == (Verdict.NOTHING, why)


# ---- the policy decides before the model -------------------------------------------------------------------


async def test_in_quiet_hours_the_model_is_not_asked(w):
    w.clock.now = T0.replace(hour=23, minute=30)
    asked = len(w.llm_requests)
    await w.svc.check_in(time(23, 30))
    assert len(w.llm_requests) == asked and traces(w)[0]["items"][0]["verdict"] == Verdict.QUIET


async def test_with_the_budget_spent_the_model_is_not_asked(w):
    state = await w.svc.wakes.load()
    state.day, state.sent = EVE.date().isoformat(), 3
    await w.svc.wakes.save(state)
    asked = len(w.llm_requests)
    await w.svc.check_in(time(21))
    assert len(w.llm_requests) == asked and traces(w)[0]["items"][0]["verdict"] == Verdict.BUDGET


async def test_one_check_in_is_told_once_a_day(w):
    w.llm_script = [say("One.")]
    await w.svc.check_in(time(21))
    asked = len(w.llm_requests)
    await w.svc.check_in(time(21))  # a restart that fires it again
    assert len(w.llm_requests) == asked and traces(w)[-1]["items"][0]["verdict"] == Verdict.REPEAT


async def test_two_thumbs_down_on_check_ins_mute_them(w):
    for at in (time(21), time(21, 30)):
        w.llm_script = [say(f"At {at}.")]
        await w.svc.check_in(at)
        await w.send("sense.feedback", Envelope(source="telegram").stamp(ref=unasked(w)[-1]["id"], vote=-1))
    assert set((await w.svc.wakes.load()).downvotes) == {CHECKIN}
    asked = len(w.llm_requests)
    await w.svc.check_in(time(22))
    assert len(w.llm_requests) == asked and traces(w)[-1]["items"][0]["verdict"] == Verdict.MUTED


async def test_a_chat_in_progress_puts_it_off_and_too_late_lets_it_go(w):
    w.svc.wake = w.svc.wake.model_copy(update={"checkin_late_s": 0})
    await write(w, ago=timedelta(minutes=1))
    asked = len(w.llm_requests)
    await w.svc.check_in(time(21))
    assert len(w.llm_requests) == asked and traces(w)[-1]["items"][0]["verdict"] == Verdict.BUSY


async def test_put_off_by_a_turn_running_it_comes_once_the_turn_is_done(w):
    w.svc.wake = w.svc.wake.model_copy(update={"busy_s": 0.05})
    lock = w.svc._lock("telegram", "123")
    await lock.acquire()  # a turn running in the home thread

    async def done_soon():
        await asyncio.sleep(0.12)
        lock.release()

    task = asyncio.create_task(done_soon())
    w.llm_script = [say(NOTHING_TODAY)]
    await w.svc.check_in(time(21))
    await task
    assert [o["text"] for o in unasked(w)] == [NOTHING_TODAY]


async def test_before_hansen_has_written_anywhere_it_is_a_notification():
    bus = InMemoryBus()
    world = World(bus, [say(NOTHING_TODAY)])
    await world.start()
    svc = MainService(bus, ThreadStore(InMemoryKV()), wake=WakePolicy(every_s=0, checkins=()), clock=Clock(EVE))
    await svc.start()
    await svc.check_in(time(21))
    assert [d["text"] for _, d in bus.events("out.notify")] == [NOTHING_TODAY]
    (note,) = world.llm_requests[-1]["messages"]  # no thread: only the note
    assert note["content"].startswith("(A note from Main's code")


async def test_the_loop_checks_in_at_its_time():
    bus = InMemoryBus()
    world = World(bus, [say(NOTHING_TODAY)])
    await world.start()
    soon = (datetime.now(UTC) + timedelta(seconds=0.3)).astimezone(TPE).time()
    policy = WakePolicy(every_s=0, quiet=None, checkins=(soon,))  # the real clock: any hour
    svc = MainService(bus, ThreadStore(InMemoryKV()), wake=policy)
    await svc.start()
    try:
        for _ in range(40):
            if bus.events("out.notify"):
                break
            await asyncio.sleep(0.05)
        assert [d["text"] for _, d in bus.events("out.notify")] == [NOTHING_TODAY]
    finally:
        await svc.stop()
        await svc.drain()


# ---- the prompt and the setting -----------------------------------------------------------------------------


def test_the_morning_looks_at_the_day_ahead_and_the_evening_at_what_is_open():
    morning = checkin_prompt(EVE.date(), "Asia/Taipei", time(8, 30), "telegram", None, []).system
    evening = checkin_prompt(EVE.date(), "Asia/Taipei", time(21), "", None, []).system
    assert (
        "the morning check-in: look at the day ahead" in morning and "the chat Hansen last used (telegram)" in morning
    )
    assert "the evening check-in: look at what is still open today" in evening
    assert "a notification (Hansen has not chatted yet)" in evening


@pytest.mark.parametrize(
    ("raw", "times"),
    [("08:30,21:00", (time(8, 30), time(21))), (" 21:00, 08:30 ,21:00", (time(8, 30), time(21))), ("", ())],
)
def test_check_in_times_read_sorted_once_each(raw, times):
    assert checkin_times(raw) == times


def test_a_check_in_time_that_does_not_read_is_refused():
    with pytest.raises(ValueError, match="HH:MM times separated by commas"):
        checkin_times("9pm")
    with pytest.raises(ValueError):
        MainSettings.model_validate({"MAIN_CHECKINS": "8.30"})


# ---- what the review found ----------------------------------------------------------------------------------


async def test_a_check_in_hours_late_is_let_go_and_its_day_keeps_its_own(w):
    w.clock.now = (EVE + timedelta(days=1)).replace(hour=10)  # the host slept through yesterday's 21:00
    await w.svc.check_in(time(21), due=EVE)
    asked = len(w.llm_requests)
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.EXPIRED and len(w.llm_requests) == asked
    w.clock.now = EVE + timedelta(days=1)
    w.llm_script = [say(NOTHING_TODAY)]
    await w.svc.check_in(time(21))  # that day's own: not a repeat of the late one
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.SENT


async def test_memory_is_opened_for_yesterday_today_and_tomorrow(w):
    queries = []
    real = w.svc._recall

    async def spy(query):
        queries.append(query)
        return await real(query)

    w.svc._recall = spy
    w.llm_script = [call("stay_quiet", {"why": "x"})]
    await w.svc.check_in(time(21))
    assert queries == ["2026-11-10, 2026-11-11, 2026-11-12: plans, appointments, birthdays and things to do"]


async def test_the_chat_is_read_as_words_only(w):
    w.clock.now = T0
    w.llm_script = [call("remember", {"note": "mei", "fact": "likes ramen"}), say("Saved.")]
    await write(w, "mei likes ramen")
    w.clock.now = EVE
    w.llm_script = [call("stay_quiet", {"why": "x"})]
    await w.svc.check_in(time(21))
    sent = w.llm_requests[-1]["messages"]
    assert all(isinstance(m["content"], str) or all(b["type"] == "text" for b in m["content"]) for m in sent)
    assert any("Saved." in str(m["content"]) for m in sent)


async def test_a_frozen_clock_still_ends_the_wait(w):
    w.svc.wake = w.svc.wake.model_copy(update={"busy_s": 0.01, "checkin_late_s": 0.03})
    await w.svc._lock("telegram", "123").acquire()  # a turn that never ends
    await w.svc.check_in(time(21))
    assert traces(w)[-1]["items"][0]["verdict"] in (Verdict.BUSY, Verdict.EXPIRED)


async def test_quiet_stays_quiet_and_a_message_held_back_is_not_traced_as_said(w):
    busy = iter([False, True])
    w.svc._busy = lambda where, now: _now(next(busy, True))
    w.llm_script = [say(NOTHING_TODAY)]
    await w.svc.check_in(time(21))  # Hansen started chatting while it looked
    item = traces(w)[-1]["items"][0]
    assert (item["verdict"], item["text"]) == (Verdict.BUSY, "the 21:00 check-in") and unasked(w) == []

    busy = iter([False, True])
    w.llm_script = [call("stay_quiet", {"why": "nothing open"})]
    await w.svc.check_in(time(21, 30))
    item = traces(w)[-1]["items"][0]
    assert (item["verdict"], item["text"]) == (Verdict.NOTHING, "nothing open")


async def _now(value):
    return value


async def test_a_message_the_bus_would_not_take_is_traced(w):
    async def broken(*a, **k):
        raise ConnectionError("nats reconnecting")

    w.svc._say_at = broken
    w.llm_script = [say(NOTHING_TODAY)]
    await w.svc.check_in(time(21))
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.FAILED and plans(w)
    assert (await w.svc.wakes.load()).sent == 0


async def test_its_message_is_kept_with_the_calls_behind_it(w):
    w.llm_script = [call("ask_module", {"module": "expenses", "action": "summary"}), say(NOTHING_TODAY)]
    await w.svc.check_in(time(21))
    await w.svc.drain()
    kept = (await w.svc.store.load("telegram", "123")).turns[-1]
    assert [c.name for c in kept.calls] == ["ask_module"]


def test_check_ins_are_off_unless_given():
    assert WakePolicy().checkins == ()
    assert MainSettings.model_validate({}).checkins == "08:30,21:00"  # the service's own default turns them on


async def test_an_empty_answer_is_asked_once_for_a_choice(w):
    w.llm_script = [say(""), call("stay_quiet", {"why": "nothing open"})]
    await w.svc.check_in(time(21))
    assert traces(w)[-1]["items"][0]["text"] == "nothing open"
    assert w.llm_requests[-1]["messages"][-1]["content"][-1]["text"] == CHOOSE
