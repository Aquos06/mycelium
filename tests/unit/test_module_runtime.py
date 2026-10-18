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
