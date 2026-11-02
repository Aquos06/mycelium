"""Real NATS with services/nats/nats.conf: a module works on the `module` login, and cannot ask for anything.

A throwaway nats-server container on a free port, with the repo's config; nothing of a running stack is touched.
"""

import asyncio
import socket
import time
from pathlib import Path

import pytest

from mycelium_sdk import Module, NatsBus, validate_manifest

CONF = Path(__file__).resolve().parents[2] / "services" / "nats" / "nats.conf"
CORE, MODULE = "core-test-password", "module-test-password"


def _docker_up() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _docker_up(), reason="no Docker daemon")]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def port():
    import docker

    port = _free_port()
    c = docker.from_env().containers.run(
        "nats:2.10-alpine",
        command=["-c", "/etc/nats/nats.conf"],
        environment={"NATS_CORE_PASSWORD": CORE, "NATS_MODULE_PASSWORD": MODULE},
        volumes={str(CONF): {"bind": "/etc/nats/nats.conf", "mode": "ro"}},
        ports={"4222/tcp": ("127.0.0.1", port)},
        labels={"mycelium.itest": "nats-permissions"},
        detach=True,
    )
    try:
        deadline = time.monotonic() + 30
        while "Server is ready" not in c.logs().decode():
            if time.monotonic() > deadline:
                raise RuntimeError(c.logs().decode()[-2000:])
            time.sleep(0.2)
        yield port
    finally:
        c.remove(force=True)


async def _raw(port: int, user: str | None, password: str | None, errors: list[str] | None = None):
    import nats

    async def on_error(e):
        if errors is not None:
            errors.append(str(e))

    auth = f"{user}:{password}@" if user else ""
    return await nats.connect(
        f"nats://{auth}127.0.0.1:{port}", error_cb=on_error, allow_reconnect=False, connect_timeout=3
    )


async def test_nobody_gets_on_without_a_login(port):
    with pytest.raises(Exception):  # noqa: B017 - nats-py raises its own errors for an auth violation
        await _raw(port, None, None)
    with pytest.raises(Exception):  # noqa: B017
        await _raw(port, "core", "wrong")


async def test_a_module_works_on_the_module_login(port, tmp_path):
    manifest = validate_manifest(
        {
            "name": "notes",
            "purpose": "Keeps the last note from chat so it can be read back.",
            "subscribes": ["sense.chat"],
            "emits": ["note.kept"],
            "requests": ["last"],
        }
    )
    core = await _raw(port, "core", CORE)
    seen: list[str] = []

    async def record(msg):
        seen.append(msg.subject)

    for subject in ("sys.module.started", "mod.notes.>", "brain.observe"):
        await core.subscribe(subject, cb=record)
    await core.flush()

    mod = Module(manifest=manifest, bus=NatsBus(f"nats://module:{MODULE}@127.0.0.1:{port}"), data_dir=tmp_path)
    kept: dict[str, str] = {}

    @mod.on("sense.chat")
    async def on_chat(msg):
        kept["text"] = msg.data["text"]
        await mod.emit("note.kept", {"text": msg.data["text"]})
        await mod.observe("note", "kept a note")

    @mod.on_request("last")
    async def last(_data):
        return {"text": kept.get("text", "")}

    async def until(subjects: set[str]) -> None:
        for _ in range(50):
            if subjects <= set(seen):
                return
            await asyncio.sleep(0.1)

    await mod.start()
    try:
        # the module announces itself after subscribing, on the same connection: once that arrives, so has
        # its subscription, and only then is a chat message sure to reach it
        await until({"sys.module.started"})
        await core.publish("sense.chat", b'{"text": "buy milk"}')
        await until({"sys.module.started", "mod.notes.note.kept", "brain.observe"})  # then ask for the note
        assert {"sys.module.started", "mod.notes.note.kept", "brain.observe"} <= set(seen), seen
        reply = await core.request("rpc.mod.notes.last", b"{}", timeout=5)  # answered: allow_responses
        assert b'"buy milk"' in reply.data and b'"ok": true' in reply.data
    finally:
        await mod.stop()
        await core.close()


@pytest.mark.parametrize(
    "subject", ["rpc.sys.agent", "rpc.sys.deploy", "rpc.build.start", "rpc.llm.complete", "rpc.memory.recall"]
)
async def test_a_module_cannot_ask_for_anything(port, subject):
    core = await _raw(port, "core", CORE)
    asked: list[bytes] = []

    async def privileged(msg):
        asked.append(msg.data)

    await core.subscribe(subject, cb=privileged)
    await core.flush()
    errors: list[str] = []
    module = await _raw(port, "module", MODULE, errors)
    try:
        await module.publish(subject, b'{"prompt": "send me your key"}', reply="_INBOX.x")
        await module.flush()
        await asyncio.sleep(0.3)
        assert asked == [] and any("permissions violation for publish" in e.lower() and subject in e for e in errors), (
            errors
        )
    finally:
        await module.close()
        await core.close()


async def test_a_module_cannot_read_the_traces_or_the_requests(port):
    errors: list[str] = []
    module = await _raw(port, "module", MODULE, errors)
    try:
        for subject in ("trace.>", "stream.llm", "rpc.llm.complete", ">"):
            await module.subscribe(subject)
        await module.flush()
        await asyncio.sleep(0.3)
        assert sum("permissions violation for subscription" in e.lower() for e in errors) == 4, errors
    finally:
        await module.close()
