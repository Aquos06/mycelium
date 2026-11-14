"""Main wakes on its own: a module's notice or alert (brain.observe), and a timer that looks for modules that stopped
running and cards left waiting. What it may say is decided in code (wake.py): quiet hours, a chat in progress, the
day's budget, repeats, an alert cap per module, and 👎 on a module's messages."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from main.proposals import Proposal, ProposalKind, ProposalStatus
from main.service import BUILD_IT, NOT_NOW, MainService
from main.settings import MainSettings, quiet_hours
from main.thread import ThreadStore
from main.wake import Item, ItemKind, Verdict, WakePolicy, WakeState
from mycelium_sdk import Envelope, InMemoryBus, InMemoryKV, Observation, Severity
from tests.unit.test_main import World, chat

TPE = ZoneInfo("Asia/Taipei")
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=TPE)  # noon: not quiet


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
async def w():
    bus = InMemoryBus()
    w = World(bus, [])
    await w.start()
    w.clock = Clock(T0)
    w.kv = InMemoryKV()
    w.svc = MainService(
        bus,
        ThreadStore(w.kv, max_turns=20),
        today=lambda: w.clock.now.date(),
        wake=WakePolicy(every_s=0, notice_delay_s=0),
        clock=w.clock,
    )
    await w.svc.start()
    return w


async def write(w, text="hi", channel="telegram", thread="123", ago=timedelta(hours=1)):
    """Hansen writes, `ago` before the clock: where Hansen writes is where Main writes first."""
    data = {**chat(text, channel, thread).data, "ts": (w.clock.now - ago).isoformat()}
    await w.send("sense.chat", data)


async def observe(
    w, summary="Nothing logged today.", severity="notice", source="expenses", type="nothing_logged", **kw
):
    obs = Observation(
        source=source, type=type, summary=summary, severity_hint=Severity(severity), ts=w.clock.now.isoformat(), **kw
    )
    await w.send("brain.observe", obs.model_dump(mode="json"))
    return obs


def unasked(w) -> list[dict]:
    """What Main said that nobody asked for: out.say not caused by a chat message."""
    return [d for _, d in w.bus.events("out.say") if not str(d["text"]).startswith("re:")]


def traces(w) -> list[dict]:
    return [d for _, d in w.bus.events("trace.wake")]


# ---- the policy, alone -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("at", "quiet"),
    [
        (time(23), True),
        (time(2), True),
        (time(7, 59), True),
        (time(8), False),
        (time(12), False),
        (time(22, 59), False),
    ],
)
def test_quiet_hours_cross_midnight(at, quiet):
    assert WakePolicy().is_quiet(at) is quiet


def test_quiet_hours_within_a_day_and_none():
    assert WakePolicy(quiet=(time(13), time(14))).is_quiet(time(13, 30))
    assert not WakePolicy(quiet=(time(13), time(14))).is_quiet(time(12))
    assert not WakePolicy(quiet=None).is_quiet(time(3))


def test_quiet_hours_setting():
    assert quiet_hours("23:00-08:00") == (time(23), time(8))
    assert quiet_hours(" ") is None
    for bad in ("23:00", "11pm-8am", "08:00-08:00", "23:00Z-08:00Z"):  # a zone of their own breaks the comparison
        with pytest.raises(ValueError):
            quiet_hours(bad)
    with pytest.raises(ValueError):
        MainSettings(MAIN_QUIET_HOURS="late")
    with pytest.raises(ValueError):  # without the timer, nothing held would ever be tried again
        MainSettings(MAIN_WAKE_EVERY=0)


def item(alert=False, source="expenses", since=T0, key="observe/expenses/x/1") -> Item:
    return Item(
        kind=ItemKind.OBSERVE,
        key=key,
        source=source,
        text="expenses: x",
        since=since.isoformat(),
        alert=alert,
        ref="o1",
    )


@pytest.mark.parametrize(
    ("state", "kw", "now", "busy", "verdict"),
    [
        (WakeState(), {}, T0, False, Verdict.SENT),
        (WakeState(downvotes={"expenses": {"m1": "t", "m2": "t"}}), {"alert": True}, T0, False, Verdict.MUTED),
        (WakeState(told={"observe/expenses/x/1": "t"}), {}, T0, False, Verdict.REPEAT),
        (WakeState(told={"observe/expenses/x/1": "t"}), {"alert": True}, T0, False, Verdict.SENT),  # an event again
        (WakeState(), {"since": T0 - timedelta(hours=11)}, T0, False, Verdict.EXPIRED),
        (WakeState(), {}, T0.replace(hour=23, minute=30), False, Verdict.QUIET),
        (WakeState(), {"alert": True}, T0.replace(hour=2), True, Verdict.SENT),  # an alert: quiet, busy, it goes
        (WakeState(sent=9), {"alert": True}, T0, False, Verdict.SENT),  # and over the budget
        (WakeState(alerts={"expenses": ["t"]}), {"alert": True}, T0.replace(hour=2), False, Verdict.QUIET),  # 2nd/hour
        (WakeState(downvotes={"expenses": {"m1": "t"}}), {"alert": True}, T0.replace(hour=2), False, Verdict.QUIET),
        (WakeState(), {}, T0, True, Verdict.BUSY),
        (WakeState(sent=3), {}, T0, False, Verdict.BUDGET),
        (WakeState(downvotes={"main": {"m1": "t", "m2": "t"}}), {"source": "main"}, T0, False, Verdict.SENT),
    ],
)
def test_judge(state, kw, now, busy, verdict):
    assert WakePolicy().judge(item(**{"since": now, **kw}), state, now, TPE, busy) == verdict


def test_tidy_starts_a_new_day_and_lets_old_things_go():
    p = WakePolicy()
    old, fresh = (T0 - timedelta(days=2)).isoformat(), (T0 - timedelta(minutes=5)).isoformat()
    state = WakeState(
        day="2026-11-10",
        sent=3,
        told={"a": old, "b": fresh},
        alerts={"expenses": [old]},
        downvotes={"x": {"m1": (T0 - timedelta(days=8)).isoformat()}, "y": {"m2": fresh}},
    )
    p.tidy(state, T0, TPE)
    assert (state.day, state.sent) == ("2026-11-11", 0)
    assert list(state.told) == ["b"] and state.alerts == {} and list(state.downvotes) == ["y"]


def test_held_observations_are_short_and_capped_per_module():
    """No data, and five a module: one noisy module never pushes out another's, and the state stays small."""
    p, state = WakePolicy(), WakeState()

    def obs(source, n, summary=None):
        return Observation(
            source=source,
            type=f"t{n}",
            summary=summary or f"Note {n}.",
            severity_hint=Severity.NOTICE,
            data={"rows": [1] * 1000},
        )

    assert p.hold(state, obs("cameras", 0), TPE)
    for n in range(8):
        p.hold(state, obs("expenses", n), TPE)
    assert not p.hold(state, obs("expenses", 7), TPE)  # the same thing waits already
    assert [o.source for o in state.held].count("expenses") == 5 and state.held[0].source == "cameras"
    assert all(o.data == {} for o in state.held)
    p.hold(state, obs("garden", 1, summary="x" * 5000), TPE)
    assert len(state.held[-1].summary) <= 300


def test_the_sdks_error_reports_are_one_thing_a_day():
    """An exception's text changes each time, so a module's error reports share one key for the day."""
    a = Observation(source="expenses", type="hook.error", summary="hourly failed: KeyError 'a'", ts=T0.isoformat())
    b = a.model_copy(update={"summary": "hourly failed: ValueError '12a'"})
    tomorrow = a.model_copy(update={"ts": (T0 + timedelta(days=1)).isoformat()})
    assert Item.of(a, TPE).key == Item.of(b, TPE).key != Item.of(tomorrow, TPE).key
    note = Observation(source="expenses", type="nothing_logged", summary="Nothing logged today.", ts=T0.isoformat())
    assert Item.of(note, TPE).key != Item.of(note.model_copy(update={"summary": "Other."}), TPE).key


def test_a_vote_counts_for_the_module_its_message_came_from():
    p, state = WakePolicy(), WakeState(replies={"m1": "expenses", "m2": "main"})
    assert p.vote(state, "m1", -1, T0) == "expenses" and len(state.downvotes["expenses"]) == 1
    p.vote(state, "m1", -1, T0)  # the same message again (voted, unvoted, voted): still one
    assert len(state.downvotes["expenses"]) == 1
    assert p.vote(state, "m2", -1, T0) is None and "main" not in state.downvotes
    assert p.vote(state, "other", -1, T0) is None
    p.vote(state, "m1", 1, T0)
    assert "expenses" not in state.downvotes


# ---- a module's notice and alert -----------------------------------------------------------------------


async def test_a_notice_is_told_in_the_thread_hansen_last_wrote_in(w):
    await write(w, "dinner 350")
    obs = await observe(w)
    (said,) = unasked(w)
    assert (said["channel"], said["thread"], said["text"]) == ("telegram", "123", "expenses: Nothing logged today.")
    assert said["cause"] == obs.id
    thread = await w.svc.store.load("telegram", "123")
    assert thread.turns[-1].text == "expenses: Nothing logged today."  # a reply to it is read with it
    assert thread.turns[-1].unasked and not thread.turns[-2].unasked
    (trace,) = traces(w)
    assert trace["reason"] == "notice" and trace["sent_today"] == 1
    assert trace["items"][0]["verdict"] == "sent" and trace["items"][0]["reply_id"] == said["id"]


async def test_info_wakes_nothing(w):
    await write(w)
    await observe(w, "Added expense: lunch (120)", severity="info")
    assert not unasked(w) and not traces(w)
    assert (await w.svc.wakes.load()).held == []


async def test_before_hansen_writes_anywhere_it_is_an_unaddressed_notify(w):
    await observe(w)
    assert not unasked(w)
    ((_, note),) = w.bus.events("out.notify")
    assert note["text"] == "expenses: Nothing logged today." and "channel" not in note


async def test_mctl_is_not_home(w):
    await write(w, channel="cli", thread="test")
    await observe(w)
    assert not unasked(w) and w.bus.events("out.notify")


async def test_the_home_follows_hansen(w):
    await write(w, channel="telegram", thread="123")
    await write(w, channel="web", thread="w1")
    await observe(w)
    (said,) = unasked(w)
    assert (said["channel"], said["thread"]) == ("web", "w1")


async def test_the_same_notice_twice_in_a_day_is_told_once(w):
    await write(w)
    await observe(w)
    await observe(w)
    assert len(unasked(w)) == 1
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.REPEAT


async def test_the_same_notice_the_next_day_is_news_again(w):
    """A repeat is the same words on the same day: a daily check told late one day is still told the next."""
    await write(w)
    await observe(w)
    w.clock.now = (T0 + timedelta(days=1)).replace(hour=9)  # 21 hours on: past the hold and repeat windows alike
    await write(w)
    await observe(w)
    assert [d["text"] for d in unasked(w)] == ["expenses: Nothing logged today."] * 2


async def test_a_notice_without_a_summary_is_not_told(w):
    await write(w)
    await observe(w, "   ")
    assert not unasked(w) and not traces(w)


async def test_a_notice_that_comes_during_a_wake_gets_its_own(w):
    """Notices that come together are one wake; one that comes while that wake runs is not left for the timer."""
    import asyncio

    w.svc.wake = WakePolicy(every_s=0, notice_delay_s=0.01)
    await write(w)
    started, go_on = asyncio.Event(), asyncio.Event()
    real = w.svc.wake_up

    async def slow(reason):
        await real(reason)  # it has read what is held and told it
        started.set()
        await go_on.wait()  # and is not done yet (publishing its trace)

    w.svc.wake_up = slow
    await observe(w, "One.", type="a")
    await asyncio.wait_for(started.wait(), 1)
    await observe(w, "Two.", type="b")  # after the first wake read the state, before it finished
    w.svc.wake_up = real
    go_on.set()
    for _ in range(100):
        if len(unasked(w)) == 2:
            break
        await asyncio.sleep(0.01)
    assert [d["text"] for d in unasked(w)] == ["expenses: One.", "expenses: Two."]


async def test_a_wake_stopped_halfway_never_tells_twice(w):
    """The state is saved after each message told: a wake cut off after the first does not repeat it."""
    import asyncio

    w.svc.wake = WakePolicy(every_s=0, notice_delay_s=0, quiet=(time(11), time(13)))
    await write(w)
    await observe(w, "One.", type="a")
    await observe(w, "Two.", type="b")  # both held: quiet until 13:00
    real, calls = w.svc._say_unasked, []

    async def say(item):
        calls.append(item.text)
        if len(calls) == 2:
            raise asyncio.CancelledError  # Main stopping (stop() cancels the ticker mid-wake)
        return await real(item)

    w.svc._say_unasked = say
    w.clock.now = T0.replace(hour=13, minute=5)
    with pytest.raises(asyncio.CancelledError):
        await w.svc.wake_up("timer")
    w.svc._say_unasked = real
    await w.svc.wake_up("timer")
    assert [d["text"] for d in unasked(w)] == ["expenses: One.", "expenses: Two."]


async def test_an_alert_does_not_wait_for_a_turn(w):
    """An alert goes out while a turn runs in the thread; it joins the thread when the turn is done."""
    import asyncio

    await write(w)
    obs = Observation(
        source="door", type="open", summary="Door opened.", severity_hint=Severity.ALERT, ts=T0.isoformat()
    )
    async with w.svc._lock("telegram", "123"):
        await w.bus.publish("brain.observe", obs.model_dump(mode="json"))  # no drain: the turn holds the thread
        for _ in range(100):
            if unasked(w):
                break
            await asyncio.sleep(0.01)
        assert unasked(w)[-1]["text"] == "door: Door opened."
        assert (await w.svc.store.load("telegram", "123")).turns[-1].text != "door: Door opened."
    await w.svc.drain()
    assert (await w.svc.store.load("telegram", "123")).turns[-1].text == "door: Door opened."


async def test_the_same_alert_hours_later_is_news(w):
    await write(w)
    await observe(w, "Front door opened.", severity="alert", source="door", type="open")
    w.clock.now += timedelta(hours=2, minutes=30)
    await observe(w, "Front door opened.", severity="alert", source="door", type="open")
    assert [d["text"] for d in unasked(w)] == ["door: Front door opened."] * 2


async def test_a_vote_that_is_not_a_number_never_breaks_the_answer(w):
    await write(w)
    fb = Envelope(source="web").stamp(ref="x", vote="up", answer="yes", channel="telegram", thread="123")
    await w.send("sense.feedback", fb)
    assert w.bus.events("trace.plan")[-1][1]["input"] == "yes"  # the answer still went on as a message


async def test_a_notice_in_quiet_hours_waits_for_the_morning(w):
    await write(w)
    w.clock.now = T0.replace(hour=23, minute=30)
    await observe(w, "Backup failed.", type="backup")
    assert not unasked(w)
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.QUIET
    w.clock.now = T0.replace(hour=2)
    await w.svc.wake_up("timer")
    assert len(traces(w)) == 1  # held for the same reason: nothing new to trace
    w.clock.now = (T0 + timedelta(days=1)).replace(hour=8, minute=15)
    await w.svc.wake_up("timer")
    (said,) = unasked(w)
    assert said["text"] == "expenses: Backup failed."
    assert (await w.svc.wakes.load()).held == []


async def test_a_notice_held_too_long_is_dropped(w):
    await write(w)
    w.clock.now = T0.replace(hour=23, minute=1)
    await observe(w, "Nothing logged today.")
    w.clock.now = (T0 + timedelta(days=1)).replace(hour=9, minute=30)  # 10.5 hours later
    await w.svc.wake_up("timer")
    assert not unasked(w)
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.EXPIRED


async def test_an_alert_interrupts_quiet_hours_once_an_hour(w):
    await write(w)
    w.clock.now = T0.replace(hour=2)
    await observe(w, "Unknown person at the front door.", severity="alert", source="cameras", type="person")
    await observe(w, "Unknown person at the back door.", severity="alert", source="cameras", type="person")
    (said,) = unasked(w)
    assert said["text"] == "cameras: Unknown person at the front door."
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.QUIET  # the second is a notice now: held


async def test_not_while_hansen_is_writing(w):
    await write(w, ago=timedelta(minutes=1))
    await observe(w)
    assert not unasked(w)
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.BUSY
    w.clock.now = T0 + timedelta(minutes=10)
    await w.svc.wake_up("timer")
    assert len(unasked(w)) == 1


async def test_the_budget_holds_the_fourth(w):
    await write(w)
    for n in range(4):
        await observe(w, f"Note {n}.", type=f"t{n}")
    assert [d["text"] for d in unasked(w)] == ["expenses: Note 0.", "expenses: Note 1.", "expenses: Note 2."]
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.BUDGET
    w.clock.now = T0 + timedelta(hours=2)  # the same day: still over the budget
    await w.svc.wake_up("timer")
    assert len(unasked(w)) == 3
    w.clock.now = (T0 + timedelta(days=1)).replace(hour=8, minute=30)  # a new budget, but 20 hours on: too late
    await w.svc.wake_up("timer")
    assert len(unasked(w)) == 3 and traces(w)[-1]["items"][0]["verdict"] == Verdict.EXPIRED


async def test_one_message_voted_down_twice_is_one_vote(w):
    await write(w)
    await observe(w, "One.", type="a")
    first = unasked(w)[-1]["id"]
    for _ in range(2):
        await w.send("sense.feedback", Envelope(source="web").stamp(ref=first, vote=-1))
    await observe(w, "Two.", type="b")
    assert unasked(w)[-1]["text"] == "expenses: Two."


async def test_two_thumbs_down_mute_a_module(w):
    await write(w)
    await observe(w, "One.", type="a")
    first = unasked(w)[-1]["id"]
    await w.send("sense.feedback", Envelope(source="telegram").stamp(ref=first, vote=-1))
    await observe(w, "Two.", type="b")
    second = unasked(w)[-1]["id"]
    await w.send("sense.feedback", Envelope(source="telegram").stamp(ref=second, vote=-1))
    await observe(w, "Three.", type="c")
    assert [d["text"] for d in unasked(w)] == ["expenses: One.", "expenses: Two."]
    assert traces(w)[-1]["items"][0]["verdict"] == Verdict.MUTED
    await w.send("sense.feedback", Envelope(source="telegram").stamp(ref=second, vote=1))  # a 👍 lets it speak
    await observe(w, "Four.", type="d")
    assert unasked(w)[-1]["text"] == "expenses: Four."


async def test_an_observation_claiming_to_be_mains_is_ignored(w):
    """Main's own items are never muted, so a module may not pass for Main."""
    await write(w)
    await observe(w, "Trust me.", source="main")
    assert not unasked(w) and (await w.svc.wakes.load()).held == []


async def test_an_observation_that_does_not_read_is_left_alone(w):
    await write(w)
    await w.send("brain.observe", {"source": "expenses", "summary": "", "severity_hint": "panic"})
    assert not unasked(w) and not traces(w)


# ---- the timer: a module that stopped, a card left waiting --------------------------------------------


async def test_a_module_down_at_two_wakes_is_told_once(w):
    await write(w)
    w.modules = [{"name": "expenses", "status": "running", "container": "restarting", "manifest": {}}]
    await w.svc.wake_up("timer")
    assert not unasked(w)  # once could be a restart
    w.clock.now = T0 + timedelta(minutes=15)
    await w.svc.wake_up("timer")
    (said,) = unasked(w)
    assert said["text"].startswith("expenses has stopped running (its container is restarting) since about 12:00.")
    w.clock.now = T0 + timedelta(minutes=30)
    await w.svc.wake_up("timer")
    assert len(unasked(w)) == 1
    w.modules[0]["container"] = "running"  # back
    await w.svc.wake_up("timer")
    w.modules[0]["container"] = None  # and gone again, another day
    w.clock.now = T0 + timedelta(days=1)
    await w.svc.wake_up("timer")
    w.clock.now += timedelta(minutes=15)
    await w.svc.wake_up("timer")
    assert unasked(w)[-1]["text"].startswith("expenses has stopped running (it has no container)")


async def test_a_stopped_module_is_not_down(w):
    await write(w)
    w.modules = [{"name": "expenses", "status": "stopped", "container": "exited", "manifest": {}}]
    for n in range(3):
        w.clock.now = T0 + timedelta(minutes=15 * n)
        await w.svc.wake_up("timer")
    assert not unasked(w)


async def test_a_card_waiting_for_days_is_shown_once_more(w):
    p = Proposal(
        id="card1",
        name="water",
        purpose="Track how much water you drink.",
        channel="web",
        thread="w1",
        created=(T0 - timedelta(days=4)).isoformat(),
    )
    await w.svc.proposals.create(p)
    await w.svc.wake_up("timer")
    ((_, card),) = w.bus.events("out.ask")
    assert (card["channel"], card["thread"], card["choices"]) == ("web", "w1", [BUILD_IT, NOT_NOW])
    assert "The water module I offered on Sat 11-07 is still waiting: Track how much water you drink." in card["text"]
    assert (await w.svc.proposals.by_card(card["ref"])).id == "card1"  # a tap on it is a tap on the proposal
    assert (await w.svc.proposals.get("card1")).nudged
    assert (await w.svc.store.load("web", "w1")).turns[-1].unasked
    w.clock.now += timedelta(days=1)
    await w.svc.wake_up("timer")
    assert len(w.bus.events("out.ask")) == 1


@pytest.mark.parametrize(
    ("kind", "status", "days"),
    [
        (ProposalKind.NEW, ProposalStatus.PROPOSED, 1),  # too soon
        (ProposalKind.NEW, ProposalStatus.PROPOSED, 20),  # too old
        (ProposalKind.NEW, ProposalStatus.DECLINED, 4),
        (ProposalKind.DELETE, ProposalStatus.PROPOSED, 4),  # a deletion is never pushed
    ],
)
async def test_cards_left_alone(w, kind, status, days):
    p = Proposal(
        id="c",
        name="water",
        purpose="x",
        kind=kind,
        status=status,
        channel="web",
        thread="w1",
        created=(T0 - timedelta(days=days)).isoformat(),
    )
    await w.svc.proposals.create(p)
    await w.svc.wake_up("timer")
    assert not w.bus.events("out.ask")


async def test_a_card_from_mctl_is_not_pushed(w):
    p = Proposal(
        id="c", name="water", purpose="x", channel="cli", thread="t", created=(T0 - timedelta(days=4)).isoformat()
    )
    await w.svc.proposals.create(p)
    await w.svc.wake_up("timer")
    assert not w.bus.events("out.ask") and not (await w.svc.proposals.get("c")).nudged


async def test_a_card_decided_meanwhile_is_not_shown_again(w):
    """The card is read again under its thread's lock: a tap in between is never undone by the reminder."""
    p = Proposal(
        id="c", name="water", purpose="x", channel="web", thread="w1", created=(T0 - timedelta(days=4)).isoformat()
    )
    await w.svc.proposals.create(p)
    (item,) = await w.svc._waiting_cards(w.clock.now)
    p.status, p.build_id = ProposalStatus.BUILDING, "b1"  # Build it, tapped just now
    await w.svc.proposals.save(p)
    with pytest.raises(LookupError):
        await w.svc._say_unasked(item)
    fresh = await w.svc.proposals.get("c")
    assert not w.bus.events("out.ask") and fresh.status == ProposalStatus.BUILDING and fresh.build_id == "b1"


async def test_the_timer_runs_on_its_own(w):
    """MAIN_WAKE_EVERY: the ticker calls wake_up("timer"), and a failure does not stop it."""
    import asyncio

    bus = InMemoryBus()
    calls = []
    svc = MainService(bus, ThreadStore(InMemoryKV()), wake=WakePolicy(every_s=0.01), clock=Clock(T0))

    async def wake_up(reason):
        calls.append(reason)
        raise RuntimeError("supervisor away")

    svc.wake_up = wake_up
    await svc.start()
    for _ in range(50):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.01)
    await svc.stop()
    assert calls[:2] == ["timer", "timer"]
