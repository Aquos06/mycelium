import pytest

from mycelium_sdk import InMemoryBus, subject_matches
from mycelium_sdk.subjects import EVENT_STREAM_SUBJECTS


@pytest.mark.parametrize(
    "pattern,subject,expected",
    [
        ("sense.chat", "sense.chat", True),
        ("sense.chat", "sense.voice", False),
        ("sense.*", "sense.chat", True),
        ("sense.*", "sense.chat.extra", False),
        ("mod.>", "mod.hello.message.counted", True),
        ("mod.>", "mod", False),
        ("mod.*.health", "mod.hello.health", True),
        (">", "anything.at.all", True),
        ("a.b", "a", False),
    ],
)
def test_subject_matches(pattern, subject, expected):
    assert subject_matches(pattern, subject) is expected


def test_rpc_subjects_never_in_event_stream():
    # JetStream would ack requests on stream subjects and race the real responder
    assert not any(s.startswith("rpc") for s in EVENT_STREAM_SUBJECTS)


async def test_inmemory_pubsub_wildcards():
    bus = InMemoryBus()
    got = []

    async def h(msg):
        got.append(msg.subject)

    await bus.subscribe("mod.*.done", h)
    await bus.publish("mod.a.done", {})
    await bus.publish("mod.a.other", {})
    assert got == ["mod.a.done"]
    assert len(bus.published) == 2


async def test_inmemory_request_reply():
    bus = InMemoryBus()

    async def h(msg):
        await msg.respond({"echo": msg.data["x"]})

    await bus.subscribe("rpc.test.echo", h)
    assert await bus.request("rpc.test.echo", {"x": 1}) == {"echo": 1}


async def test_inmemory_request_no_responders():
    with pytest.raises(TimeoutError):
        await InMemoryBus().request("rpc.nobody", {})
