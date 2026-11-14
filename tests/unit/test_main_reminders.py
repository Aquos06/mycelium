"""Reminders Hansen sets in chat: `remind` keeps one, `cancel_reminder` takes one away, and Main's reminder loop sends
each at its minute in the thread it was set in, whatever the wake policy says."""

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from main.prompt import render_reminders
from main.reminders import Reminder, Repeat, step, when
from main.service import RECHECK, REMIND_RECHECK, MainService, _unbacked_reminder
from main.thread import ThreadStore
from main.tools import RemindArgs
from main.wake import WakePolicy
from mycelium_sdk import InMemoryBus, InMemoryKV
from tests.unit.test_main import World, call, chat, say
from tests.unit.test_main_wake import T0, TPE, Clock, write

NY = ZoneInfo("America/New_York")


@pytest.fixture
async def w():
    bus = InMemoryBus()
    w = World(bus, [])
    await w.start()
    w.clock = Clock(T0)  # Wed 2026-11-11 12:00 in Taipei
    w.svc = MainService(
        bus,
        ThreadStore(InMemoryKV(), max_turns=20),
        today=lambda: w.clock.now.date(),
        wake=WakePolicy(every_s=0, notice_delay_s=0),
        clock=w.clock,
        remind_step_s=0,  # the tests call remind_due() themselves
    )
    await w.svc.start()
    return w


def reminder(id="r1", text="Time to pay the rent.", due=T0 + timedelta(hours=1), **kw) -> Reminder:
    fields = {"channel": "telegram", "thread": "123", "created": T0.isoformat(), **kw}
    return Reminder(id=id, text=text, due=due.isoformat(), **fields)


def said(w) -> list[dict]:
    return [d for _, d in w.bus.events("out.say") if not str(d["text"]).startswith("re:")]


# ---- times -------------------------------------------------------------------------------------------


def test_each_repeat_steps_on_the_wall_clock():
    fri = datetime(2026, 11, 13, 9, 0, tzinfo=TPE)
    assert step(fri, Repeat.DAILY) == datetime(2026, 11, 14, 9, 0, tzinfo=TPE)
    assert step(fri, Repeat.WEEKDAYS) == datetime(2026, 11, 16, 9, 0, tzinfo=TPE)  # Friday -> Monday
    assert step(fri, Repeat.WEEKLY) == datetime(2026, 11, 20, 9, 0, tzinfo=TPE)
    jan31 = datetime(2027, 1, 31, 8, 0, tzinfo=TPE)
    feb = step(jan31, Repeat.MONTHLY, 31)
    assert feb == datetime(2027, 2, 28, 8, 0, tzinfo=TPE)
    assert step(feb, Repeat.MONTHLY, 31) == datetime(2027, 3, 31, 8, 0, tzinfo=TPE)  # the 31st again, where it can
    dec = datetime(2026, 12, 15, 8, 0, tzinfo=TPE)
    assert step(dec, Repeat.MONTHLY, 15) == datetime(2027, 1, 15, 8, 0, tzinfo=TPE)


def test_a_daily_time_stays_on_the_clock_across_a_summer_time_change():
    sat = datetime(2026, 10, 31, 9, 0, tzinfo=NY)  # New York leaves summer time on Sunday 2026-11-01
    sun = step(sat, Repeat.DAILY)
    assert (sun.hour, sun.minute) == (9, 0)
    assert (sun - sat) == timedelta(days=1)  # the wall clock's day
    assert (sun.astimezone(UTC) - sat.astimezone(UTC)) == timedelta(hours=25)  # the real one


def test_after_skips_the_times_missed_and_a_one_off_has_none():
    daily = reminder(due=T0 - timedelta(days=3), repeat=Repeat.DAILY)
    assert daily.after(T0, TPE) == T0 + timedelta(days=1)  # 12:00 tomorrow, not each missed day
    assert reminder(due=T0 - timedelta(days=3)).after(T0, TPE) is None


def test_a_reminder_needs_a_time_with_its_offset():
    with pytest.raises(ValidationError):
        Reminder(id="x", text="t", due="2026-11-11T12:00", channel="c", thread="t", created="")


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ({"text": "rent"}, "exactly one of"),
        ({"text": "rent", "at": "2026-11-20 09:00", "in_minutes": 5}, "exactly one of"),
        ({"text": "rent", "at": "Friday 9am"}, "YYYY-MM-DD HH:MM"),
        ({"text": "rent", "in_minutes": 0}, "greater than or equal to 1"),
        ({"text": "", "in_minutes": 5}, "at least 1 character"),
    ],
)
def test_remind_refuses_what_it_cannot_place(args, error):
    with pytest.raises(ValidationError, match=error):
        RemindArgs.model_validate(args)


# ---- setting one -------------------------------------------------------------------------------------


async def test_remind_keeps_it_for_this_thread_on_hansens_clock(w):
    w.llm_script = [
        call("remind", {"text": "Time to pay the rent.", "at": "2026-11-20 09:00", "repeat": "monthly"}),
        say("I'll remind you."),
    ]
    await w.send("sense.chat", chat("remind me on the 20th at 9 to pay rent, every month").data)
    (r,) = await w.svc.reminders.all()
    assert r.due_at() == datetime(2026, 11, 20, 9, 0, tzinfo=TPE) and r.day == 20
    assert (r.channel, r.thread, r.repeat) == ("telegram", "123", Repeat.MONTHLY)
    assert r.cause and r.created == T0.isoformat()
    result = w.llm_requests[1]["messages"][-1]["content"][0]["content"]
    assert '"when": "Fri 2026-11-20 09:00"' in result and '"repeat": "every month"' in result
    assert said(w)[-1]["text"] == "I'll remind you."  # one call went through: no second look at the claim


async def test_in_minutes_counts_from_now(w):
    w.llm_script = [call("remind", {"text": "Tea is ready.", "in_minutes": 20}), say("ok")]
    await w.send("sense.chat", chat("ping me in 20 minutes, tea").data)
    (r,) = await w.svc.reminders.all()
    assert r.due_at() == T0 + timedelta(minutes=20)


async def test_a_time_that_has_passed_goes_back_to_the_model(w):
    w.llm_script = [call("remind", {"text": "x", "at": "2026-11-11 09:00"}), say("ok")]
    await w.send("sense.chat", chat("remind me at 9").data)
    assert await w.svc.reminders.all() == []
    result = w.llm_requests[1]["messages"][-1]["content"][0]["content"]
    assert "Wed 2026-11-11 09:00 has passed: it is Wed 2026-11-11 12:00 now" in result


async def test_a_reminder_promised_in_words_gets_a_second_look(w):
    w.llm_script = [
        say("Sure, I'll remind you Friday at 9."),
        call("remind", {"text": "Pay the rent.", "at": "2026-11-13 09:00"}),
        say("Set for Friday 09:00."),
    ]
    await w.send("sense.chat", chat("remind me friday at 9 to pay rent").data)
    assert w.llm_requests[1]["messages"][-1]["content"] == REMIND_RECHECK
    assert len(await w.svc.reminders.all()) == 1
    assert said(w)[-1]["text"] == "Set for Friday 09:00."


async def test_a_save_claimed_with_only_a_reminder_set_is_asked_again(w):
    """A reminder is not memory: "saved your appointment" after only `remind` gets the memory note."""
    w.llm_script = [
        call("remind", {"text": "Dentist at 9.", "at": "2026-11-12 08:00"}),
        say("Saved your dentist appointment, and I'll remind you at 08:00."),
        say("Reminder set for 08:00."),
    ]
    await w.send("sense.chat", chat("dentist tomorrow at 9, remind me at 8").data)
    assert w.llm_requests[2]["messages"][-1]["content"] == RECHECK


async def test_a_save_and_a_reminder_both_claimed_get_both_notes(w):
    w.llm_script = [say("Noted the dentist, and I'll remind you Thursday."), say("ok")]
    await w.send("sense.chat", chat("dentist friday at 9, remind me thursday at 8pm").data)
    assert w.llm_requests[1]["messages"][-1]["content"] == f"{RECHECK}\n\n{REMIND_RECHECK}"


async def test_the_prompt_has_the_time_and_the_reminders_with_their_ids(w):
    await w.svc.reminders.save(reminder("a1b2c3", due=T0 + timedelta(days=2, hours=-3), repeat=Repeat.WEEKLY))
    await w.svc.reminders.save(reminder("d4e5f6", "Call mom.", due=T0 + timedelta(hours=1)))
    w.llm_script = [say("ok")]
    await w.send("sense.chat", chat("what reminders do I have?").data)
    system = w.llm_requests[0]["system"]
    assert "Today is Wednesday 2026-11-11 (Asia/Taipei).\n" in system  # the minute is last: the rest stays cached
    assert system.endswith(
        "Reminders (set, not sent yet; the id first):\n"
        "- d4e5f6 Wed 2026-11-11 13:00: Call mom.\n"
        "- a1b2c3 Fri 2026-11-13 09:00, every week: Time to pay the rent.\n\n"
        "It is 12:00 now."
    )


def test_a_long_list_of_reminders_is_cut():
    many = [reminder(f"r{i:02d}", due=T0 + timedelta(hours=i)) for i in range(25)]
    lines = render_reminders(many, "Asia/Taipei").splitlines()
    assert len(lines) == 21 and lines[-1] == "(and 5 more, later)"
    assert render_reminders([], "Asia/Taipei") == "(none)"


async def test_cancel_reminder_takes_it_away_and_an_unknown_id_lists_the_ones_set(w):
    await w.svc.reminders.save(reminder("a1b2c3"))
    w.llm_script = [call("cancel_reminder", {"id": "zzz"}), call("cancel_reminder", {"id": "a1b2c3"}), say("Done.")]
    await w.send("sense.chat", chat("cancel the rent reminder").data)
    first = w.llm_requests[1]["messages"][-1]["content"][0]["content"]
    assert "no reminder 'zzz'; the ones set: ['a1b2c3']" in first
    second = w.llm_requests[2]["messages"][-1]["content"][0]["content"]
    assert '"cancelled": "Time to pay the rent."' in second
    assert await w.svc.reminders.all() == []


# ---- sending it --------------------------------------------------------------------------------------


async def test_a_reminder_goes_out_at_its_time_in_its_thread_and_is_kept_there(w):
    await w.svc.reminders.save(reminder(due=T0 + timedelta(minutes=30), cause="m1"))
    assert await w.svc.remind_due() == T0 + timedelta(minutes=30)  # nothing yet: the next one is then
    assert said(w) == []
    w.clock.now = T0 + timedelta(minutes=30)
    await w.svc.remind_due()
    await w.svc.drain()
    (out,) = said(w)
    assert (out["channel"], out["thread"], out["text"]) == ("telegram", "123", "⏰ Time to pay the rent.")
    assert out["cause"] is None  # news now, not the answer to the message that set it
    thread = await w.svc.store.load("telegram", "123")
    assert thread.turns[-1].text == "⏰ Time to pay the rent." and thread.turns[-1].unasked
    assert await w.svc.reminders.all() == []  # once: gone
    ((_, trace),) = w.bus.events("trace.wake")
    assert trace["reason"] == "reminder" and trace["items"][0]["kind"] == "reminder"
    assert trace["items"][0]["reply_id"] == out["id"]
    await w.svc.remind_due()
    assert len(said(w)) == 1


async def test_a_repeating_one_moves_to_its_next_time(w):
    await w.svc.reminders.save(reminder(due=T0, repeat=Repeat.WEEKDAYS))
    await w.svc.remind_due()
    (r,) = await w.svc.reminders.all()
    assert r.due_at() == T0 + timedelta(days=1)  # Thursday


async def test_the_wake_policy_never_holds_a_reminder(w):
    w.svc.wake = WakePolicy(every_s=0, notice_delay_s=0, budget=0)  # the day's budget spent
    await write(w, "hi", ago=timedelta(seconds=10))  # a chat in progress
    w.clock.now = datetime(2026, 11, 12, 6, 30, tzinfo=TPE)  # quiet hours
    await w.svc.reminders.save(reminder(due=w.clock.now - timedelta(seconds=5)))
    await w.svc.remind_due()
    assert [d["text"] for d in said(w)] == ["⏰ Time to pay the rent."]


async def test_one_missed_while_main_was_down_says_when_it_was_due_and_is_sent_once(w):
    await w.svc.reminders.save(reminder(due=T0 - timedelta(days=2, hours=3), repeat=Repeat.DAILY))
    await w.svc.remind_due()
    (out,) = said(w)
    assert out["text"] == "⏰ (Mon 2026-11-09 09:00) Time to pay the rent."
    (r,) = await w.svc.reminders.all()
    assert r.due_at() == datetime(2026, 11, 12, 9, 0, tzinfo=TPE)


async def test_one_set_from_mctl_goes_to_the_home_thread_or_the_phone(w):
    await w.svc.reminders.save(reminder("r1", channel="mctl", thread="term", due=T0))
    await w.svc.remind_due()
    assert [d["text"] for _, d in w.bus.events("out.notify")] == ["⏰ Time to pay the rent."]
    await write(w, "hi", channel="web", thread="w1")
    await w.svc.reminders.save(reminder("r2", channel="mctl", thread="term", due=T0))
    await w.svc.remind_due()
    assert [(d["channel"], d["thread"]) for d in said(w)] == [("web", "w1")]


async def test_one_that_does_not_read_never_stops_the_others(w):
    await w.svc.store.kv.put("reminder/bad", {"id": "bad", "due": "soon"})
    await w.svc.reminders.save(reminder(due=T0))
    await w.svc.remind_due()
    assert len(said(w)) == 1


async def test_the_loop_sends_a_reminder_set_while_it_waits():
    bus = InMemoryBus()
    world = World(bus, [])
    await world.start()
    svc = MainService(bus, ThreadStore(InMemoryKV()), wake=WakePolicy(every_s=0), remind_step_s=30.0)
    await svc.start()
    try:
        await asyncio.sleep(0.05)  # the loop found nothing and waits up to 30 s
        due = datetime.now(UTC) + timedelta(seconds=0.3)
        await svc.reminders.save(reminder(due=due))
        for _ in range(40):
            if bus.events("out.say"):
                break
            await asyncio.sleep(0.05)
        ((_, out),) = bus.events("out.say")
        assert out["text"] == "⏰ Time to pay the rent."
    finally:
        await svc.stop()
        await svc.drain()


async def test_asking_twice_keeps_one_reminder(w):
    args = {"text": "Call mom.", "at": "2026-11-12 20:00"}
    w.llm_script = [call("remind", args), call("remind", args, id="t2"), say("ok")]
    await w.send("sense.chat", chat("remind me tomorrow at 8pm to call mom").data)
    assert len(await w.svc.reminders.all()) == 1
    assert '"already_set": true' in w.llm_requests[2]["messages"][-1]["content"][0]["content"]


async def test_one_cancelled_while_the_loop_looked_is_not_sent_nor_saved_back(w):
    await w.svc.reminders.save(reminder(due=T0, repeat=Repeat.DAILY))
    real_all = w.svc.reminders.all

    async def all_then_cancelled():
        found = await real_all()
        await w.svc.reminders.delete("r1")  # Hansen cancels between the look and the send
        return found

    w.svc.reminders.all = all_then_cancelled
    await w.svc.remind_due()
    assert said(w) == []
    assert await real_all() == []


async def test_a_cancel_waits_for_a_reminder_going_out(w):
    await w.svc.reminders.save(reminder(due=T0, repeat=Repeat.DAILY))
    async with w.svc.reminders.lock:  # it is going out
        w.llm_script = [call("cancel_reminder", {"id": "r1"}), say("Cancelled.")]
        turn = asyncio.create_task(w.send("sense.chat", chat("cancel the rent one", thread="9").data))
        await asyncio.sleep(0.05)
        assert not turn.done() and len(await w.svc.reminders.all()) == 1
    await turn
    assert await w.svc.reminders.all() == []


@pytest.mark.parametrize(
    ("reply", "claims"),
    [
        ("Sure, I'll remind you Friday at 9.", True),
        ("I've set a reminder for 09:00.", True),
        ("Reminder set: Fri 09:00.", True),
        ("好，我會提醒你。", True),
        ("Want me to set a reminder for that?", False),
        ("I can't set a reminder without a time: when?", False),
        ("Your rent reminder is on Friday at 09:00.", False),
        ("Should I set a reminder for Friday at 9?", False),
        ("Saved. Should I set a reminder for Friday at 9? I can.", False),
        ("好，已取消，之後不會提醒你了。", False),
        ("Your rent reminder is set for Friday 2026-11-06 at 09:00, repeating monthly.", False),
        ("Got it.\nReminder added for tomorrow 08:00.", True),
    ],
)
def test_a_promised_reminder_is_one_in_the_first_person(reply, claims):
    assert bool(_unbacked_reminder(reply, [])) is claims


def test_a_time_summer_time_skips_moves_that_day_only():
    """New York jumps from 02:00 to 03:00 on 2027-03-14: a daily 02:30 is 03:30 that day, then 02:30 again."""
    r = reminder(due=datetime(2027, 3, 13, 2, 30, tzinfo=NY), repeat=Repeat.DAILY, wall="02:30")
    sunday = r.after(datetime(2027, 3, 13, 3, 0, tzinfo=NY), NY)
    assert sunday.astimezone(UTC) == datetime(2027, 3, 14, 7, 30, tzinfo=UTC)  # 03:30 that morning
    stored = r.model_copy(update={"due": sunday.isoformat()})
    assert when(stored.due_at(), NY) == "Sun 2027-03-14 03:30"
    monday = Reminder.model_validate(stored.model_dump()).after(sunday.astimezone(UTC), NY)
    assert monday.astimezone(NY).replace(tzinfo=None) == datetime(2027, 3, 15, 2, 30)


def test_at_needs_a_time_of_day():
    with pytest.raises(ValidationError, match="needs a time of day"):
        RemindArgs.model_validate({"text": "rent", "at": "2026-11-20"})
    with pytest.raises(ValidationError, match="needs a time of day"):
        RemindArgs.model_validate({"text": "rent", "at": "20261120"})


async def test_a_weekday_reminder_set_for_a_saturday_starts_on_monday(w):
    w.clock.now = datetime(2026, 11, 14, 12, 0, tzinfo=TPE)  # a Saturday
    w.llm_script = [call("remind", {"text": "Standup.", "at": "2026-11-15 09:30", "repeat": "weekdays"}), say("ok")]
    await w.send("sense.chat", chat("every weekday at 9:30 remind me about standup").data)
    (r,) = await w.svc.reminders.all()
    assert r.due_at() == datetime(2026, 11, 16, 9, 30, tzinfo=TPE) and r.wall == "09:30"


async def test_the_same_reminder_set_in_another_chat_is_one(w):
    args = {"text": "Call mom.", "at": "2026-11-12 20:00"}
    w.llm_script = [call("remind", args), say("ok"), call("remind", args), say("ok")]
    await w.send("sense.chat", chat("remind me tomorrow at 8pm to call mom").data)
    await w.send("sense.chat", chat("remind me tomorrow at 8pm to call mom", channel="web", thread="w1").data)
    assert len(await w.svc.reminders.all()) == 1


async def test_a_move_that_fails_is_tried_again_without_sending_twice(w):
    await w.svc.reminders.save(reminder(due=T0, repeat=Repeat.DAILY))
    real_save = w.svc.reminders.save
    failing = True

    async def save(r):
        if failing:
            raise RuntimeError("the bucket is full")
        await real_save(r)

    w.svc.reminders.save = save
    await w.svc.remind_due()
    await w.svc.remind_due()
    assert len(said(w)) == 1  # sent once, though it could not be moved on
    failing = False
    await w.svc.remind_due()
    assert len(said(w)) == 1
    (r,) = await w.svc.reminders.all()
    assert r.due_at() == T0 + timedelta(days=1)


async def test_reminders_are_read_from_the_bucket_once(w):
    await w.svc.reminders.save(reminder())
    calls = 0
    real_keys = w.svc.store.kv.keys

    async def keys(prefix=""):
        nonlocal calls
        calls += 1
        return await real_keys(prefix)

    w.svc.store.kv.keys = keys
    for _ in range(3):
        await w.svc.remind_due()
    assert calls == 0
    fresh = MainService(w.bus, ThreadStore(w.svc.store.kv), remind_step_s=0)  # Main started again
    assert [r.id for r in await fresh.reminders.all()] == ["r1"] and calls == 1
