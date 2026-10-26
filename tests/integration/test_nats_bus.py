"""Real NATS: the SDK bus, a real module over the wire, and the JetStream stream setup."""

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

from mycelium_sdk import NatsBus
from tests.conftest import NATS_URL, needs_nats

pytestmark = [pytest.mark.integration, needs_nats]

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
async def bus():
    b = NatsBus(NATS_URL, name="itest")
    await b.connect()
    yield b
    await b.close()


async def test_pub_sub_roundtrip(bus):
    subject = f"sense.itest.{uuid.uuid4().hex[:8]}"
    got = asyncio.Queue()

    async def h(msg):
        await got.put(msg.data)

    await bus.subscribe(subject, h)
    await bus.flush()
    await bus.publish(subject, {"n": 1})
    assert await asyncio.wait_for(got.get(), 3) == {"n": 1}


async def test_request_reply(bus):
    subject = f"rpc.itest.{uuid.uuid4().hex[:8]}"

    async def h(msg):
        await msg.respond({"double": msg.data["x"] * 2})

    await bus.subscribe(subject, h)
    await bus.flush()
    assert await bus.request(subject, {"x": 21}) == {"double": 42}


async def test_request_without_responder_times_out(bus):
    # Two ways nobody answers, one exception: NATS says "no responders" at once on a bare server, and the SDK
    # maps it to TimeoutError; on a running stack the tracer subscribes to `>`, so the request simply times out.
    # A caller (the web gateway's 504) needs to know one exception, not nats's.
    with pytest.raises(TimeoutError):
        await bus.request(f"rpc.nobody.{uuid.uuid4().hex[:8]}", {}, timeout=0.5)


async def test_hello_module_over_real_nats(bus, tmp_path):
    sys.path.insert(0, str(REPO / "modules" / "hello"))
    try:
        from app.main import build  # the real hello module

        mod = build(
            manifest_path=REPO / "modules/hello/manifest.yaml",
            bus=NatsBus(NATS_URL, name="itest-hello"),
            data_dir=tmp_path,
        )
        await mod.start()
        try:
            await bus.publish("sense.chat", {"text": "integration"})
            await bus.flush()
            for _ in range(30):
                reply = await bus.request("rpc.mod.hello.stats", {})
                if reply["count"] >= 1:
                    break
                await asyncio.sleep(0.1)
            assert reply["ok"] is True and reply["count"] >= 1
            health = await bus.request("rpc.mod.hello.health", {})
            assert health == {"ok": True, "name": "hello", "version": "0.1.0"}
        finally:
            await mod.stop()
    finally:
        sys.path.remove(str(REPO / "modules" / "hello"))
        sys.modules.pop("app.main", None)
        sys.modules.pop("app", None)


async def test_event_stream_created_and_requests_not_captured():
    import nats

    from tracer import ensure_stream

    nc = await nats.connect(NATS_URL)
    try:
        await ensure_stream(nc, retention_days=1)
        await ensure_stream(nc, retention_days=1)  # idempotent
        js = nc.jetstream()
        info = await js.stream_info("EVENTS")
        assert "mod.>" in info.config.subjects
        assert not any(s.startswith("rpc") for s in info.config.subjects)

        # a request on rpc.* must get the real responder's answer, not a JetStream PubAck
        async def h(msg):
            await msg.respond(b'{"real": true}')

        subj = f"rpc.itest.{uuid.uuid4().hex[:8]}"
        await nc.subscribe(subj, cb=h)
        await nc.flush()
        reply = await nc.request(subj, b"{}", timeout=2)
        assert reply.data == b'{"real": true}'

        # an event on mod.* is stored: look for this message, not for a count (live services publish too)
        marker = uuid.uuid4().hex[:8]
        await nc.publish(f"mod.itest.{marker}.happened", b'{"x": 1}')
        await nc.flush()
        for _ in range(20):
            try:
                stored = await js.get_last_msg("EVENTS", f"mod.itest.{marker}.happened")
                break
            except Exception:
                await asyncio.sleep(0.1)
        else:
            raise AssertionError("published event never reached the EVENTS stream")
        assert stored.data == b'{"x": 1}'
    finally:
        await nc.drain()
