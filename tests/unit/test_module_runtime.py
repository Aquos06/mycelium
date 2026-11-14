import pytest

from mycelium_sdk import InMemoryBus, Module, validate_manifest
from mycelium_sdk.module import ContractViolation


def make(tmp_path, **over):
    manifest = validate_manifest(
        {
            "name": "demo",
            "purpose": "Demo module for runtime tests.",
            "subscribes": ["sense.chat"],
            "emits": ["thing.happened"],
            "requests": ["ping"],
            "hooks": {"interval_seconds": [60]},
            **over,
        }
    )
    bus = InMemoryBus()
    return Module(manifest=manifest, bus=bus, data_dir=tmp_path), bus


def test_undeclared_registrations_rejected(tmp_path):
    mod, _ = make(tmp_path)
    with pytest.raises(ContractViolation):
        mod.on("sense.voice")
    with pytest.raises(ContractViolation):
        mod.on_request("nope")
    with pytest.raises(ContractViolation):
        mod.every(30)


async def test_emit_enforced(tmp_path):
    mod, bus = make(tmp_path)
    await mod.emit("thing.happened", {"a": 1})
    assert bus.events("mod.demo.thing.happened") == [("mod.demo.thing.happened", {"a": 1})]
    with pytest.raises(ContractViolation):
        await mod.emit("undeclared", {})


async def test_observe_envelope(tmp_path):
    mod, bus = make(tmp_path)
    await mod.observe("x", "something happened", {"k": 1}, severity="alert")
    ((_, env),) = bus.events("brain.observe")
    assert env["source"] == "demo" and env["severity_hint"] == "alert" and env["data"] == {"k": 1}
    with pytest.raises(ValueError):
        await mod.observe("x", "y", severity="panic")


async def test_request_and_default_health(tmp_path):
    mod, bus = make(tmp_path)

    @mod.on_request("ping")
    async def ping(data):
        return {"pong": data.get("n", 0) + 1}

    await mod.start()
    assert await bus.request("rpc.mod.demo.ping", {"n": 1}) == {"ok": True, "pong": 2}
    assert (await bus.request("rpc.mod.demo.health", {}))["ok"] is True
    assert bus.events("sys.module.started")
    await mod.stop()


async def test_request_error_becomes_ok_false(tmp_path):
    mod, bus = make(tmp_path)

    @mod.on_request("ping")
    async def ping(data):
        raise ValueError("bad input")

    await mod.start()
    assert await bus.request("rpc.mod.demo.ping", {}) == {"ok": False, "error": "bad input"}
    await mod.stop()


async def test_crashing_handler_is_observed_not_fatal(tmp_path):
    mod, bus = make(tmp_path)

    @mod.on("sense.chat")
    async def boom(msg):
        raise RuntimeError("kaboom")

    await mod.start()
    await bus.publish("sense.chat", {"text": "hi"})
    errs = [d for _, d in bus.events("brain.observe") if d["type"] == "handler.error"]
    assert errs and "kaboom" in errs[0]["summary"]
    await mod.stop()


def test_today_is_the_users_day_from_tz(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    import mycelium_sdk.module as runtime

    class Clock(datetime):  # 2026-10-27 23:30 UTC is already the 28th in Taipei
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 27, 23, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(runtime, "datetime", Clock)
    mod, _ = make(tmp_path)
    assert mod.today().isoformat() == "2026-10-27"  # no TZ: UTC
    monkeypatch.setenv("TZ", "Asia/Taipei")
    mod, _ = make(tmp_path)
    assert mod.today().isoformat() == "2026-10-28" and mod.now().hour == 7
    pinned = Module(manifest=mod.manifest, bus=InMemoryBus(), data_dir=tmp_path, tz="America/New_York")
    assert pinned.today().isoformat() == "2026-10-27"
    monkeypatch.setenv("TZ", "Mars/Olympus")  # unknown: still starts, in UTC
    mod, _ = make(tmp_path)
    assert mod.tz is UTC


async def test_observe_is_an_observation_with_an_envelope(tmp_path):
    """Main reads brain.observe with the SDK's model: an id to refer to, the severity, the module as source."""
    from mycelium_sdk import Observation, Severity

    mod, bus = make(tmp_path)
    await mod.observe("nothing_logged", "Nothing logged today.", severity="notice")
    ((_, raw),) = bus.events("brain.observe")
    obs = Observation.model_validate(raw)
    assert obs.id and obs.ts and obs.source == "demo" and obs.severity_hint == Severity.NOTICE


def test_daily_hook_must_be_declared(tmp_path):
    mod, _ = make(tmp_path, hooks={"daily": ["21:00"]})
    mod.at("21:00")(_noop)
    with pytest.raises(ContractViolation):
        mod.at("08:00")


@pytest.mark.parametrize(
    ("given", "kept"),
    [(["21:00"], ["21:00"]), ([1260, "07:30"], ["21:00", "07:30"]), ([425], ["07:05"])],
)
def test_daily_times_read_as_hh_mm(given, kept):
    """YAML reads an unquoted 21:00 as 1260 (minutes): taken back as the time it was."""
    m = validate_manifest({"name": "demo", "purpose": "Demo module for runtime tests.", "hooks": {"daily": given}})
    assert m.hooks.daily == kept


@pytest.mark.parametrize("bad", [["24:00"], ["9pm"], ["21:00", "21:00"], ["21:60"]])
def test_daily_times_refused(bad):
    from mycelium_sdk import ManifestError

    with pytest.raises(ManifestError):
        validate_manifest({"name": "demo", "purpose": "Demo module for runtime tests.", "hooks": {"daily": bad}})


def test_next_daily_is_today_or_tomorrow_in_the_users_zone():
    from datetime import UTC, datetime, time
    from zoneinfo import ZoneInfo

    from mycelium_sdk.clock import next_daily

    tpe = ZoneInfo("Asia/Taipei")
    assert next_daily(datetime(2026, 11, 11, 20, 59, tzinfo=tpe), time(21)) == datetime(2026, 11, 11, 21, tzinfo=tpe)
    assert next_daily(datetime(2026, 11, 11, 21, 0, tzinfo=tpe), time(21)) == datetime(2026, 11, 12, 21, tzinfo=tpe)
    utc = datetime(2026, 11, 11, 13, 30, tzinfo=UTC)  # 21:30 in Taipei: tomorrow, in Taipei's day
    assert next_daily(utc, time(21), tpe) == datetime(2026, 11, 12, 21, tzinfo=tpe)


def test_a_day_across_a_summer_time_change_is_its_real_length():
    """Measured in UTC: two times in one zone subtract as wall clocks, which would fire an hour late."""
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    from mycelium_sdk.clock import next_daily, seconds_until

    ny = ZoneInfo("America/New_York")
    now = datetime(2026, 3, 7, 21, 0, tzinfo=ny)  # the night before clocks go forward
    due = next_daily(now, time(21))
    assert due == datetime(2026, 3, 8, 21, 0, tzinfo=ny) and seconds_until(due, now) == 23 * 3600


async def test_sleep_until_follows_the_wall_clock():
    """It looks at the clock in steps, so a host that slept (the clock jumped) is not late."""
    import asyncio
    from datetime import UTC, datetime, timedelta

    from mycelium_sdk.clock import sleep_until

    clock = [datetime(2026, 11, 11, 12, 0, tzinfo=UTC)]
    due = clock[0] + timedelta(hours=9)
    steps = 0

    async def jump():
        nonlocal steps
        while steps < 3:
            await asyncio.sleep(0)
        clock[0] = due  # the laptop woke up: hours passed in one step

    def now():
        nonlocal steps
        steps += 1
        return clock[0]

    jumper = asyncio.create_task(jump())
    assert await asyncio.wait_for(sleep_until(due, now, step=0.001), 1) is True
    await jumper
    stop = asyncio.Event()
    stop.set()
    assert await sleep_until(due + timedelta(hours=1), lambda: due, stop, step=0.001) is False


async def test_daily_hook_runs_at_its_time(tmp_path):
    """The hook waits for its time on the module's clock, runs, and a failure becomes a notice instead of stopping it."""
    import asyncio
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from mycelium_sdk import clock as clocks

    mod, bus = make(tmp_path, hooks={"daily": ["21:00"]})
    now = [datetime(2026, 11, 11, 20, 59, 58, tzinfo=ZoneInfo("Asia/Taipei"))]
    mod.now = lambda: now[0]
    ran = asyncio.Event()

    @mod.at("21:00")
    async def evening():
        ran.set()
        raise RuntimeError("table missing")

    step, clocks.STEP_S = clocks.STEP_S, 0.001
    try:
        await mod.start()
        await asyncio.sleep(0.01)
        assert not ran.is_set()  # 20:59:58: not yet
        now[0] += timedelta(seconds=2)
        await asyncio.wait_for(ran.wait(), 1)
        for _ in range(5):
            await asyncio.sleep(0)
    finally:
        clocks.STEP_S = step
        await mod.stop()
    notes = [d for _, d in bus.events("brain.observe") if d["type"] == "hook.error"]
    assert len(notes) == 1  # once: the next run is tomorrow
    assert "evening failed: table missing" in notes[0]["summary"] and notes[0]["severity_hint"] == "notice"


async def test_observe_takes_any_data(tmp_path):
    """A value JSON cannot hold is sent as its text, a number key as a string: an observation never breaks a handler."""
    mod, bus = make(tmp_path)

    class Row:
        def __str__(self):
            return "row 7"

    await mod.observe("row_added", "Added one row.", {"row": Row(), 1: "x"})
    await mod.observe("listed", "", ["a"])  # no summary: nothing to tell, but no error either
    (_, first), (_, second) = bus.events("brain.observe")
    assert first["data"] == {"row": "row 7", "1": "x"}
    assert second["data"] == {"value": ["a"]} and second["summary"] == ""


async def _noop():
    return None
