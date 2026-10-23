"""SDK: the KV abstraction and the message envelope."""

import json
import re
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from mycelium_sdk import Envelope, InMemoryBus, NatsBus, new_id, validation_message
from mycelium_sdk.kv import InMemoryKV, kv_key


def test_kv_key_sanitises_what_nats_rejects():
    assert kv_key("thread", "telegram", "123") == "thread/telegram/123"
    assert kv_key("telegram:123") == "telegram_123"
    assert kv_key("a b", "", "c") == "a_b/c"  # empty parts dropped
    assert re.fullmatch(r"[-/_=.a-zA-Z0-9]+", kv_key("x@y/z", "小美"))
    # a key is a subject: no leading / trailing dot, no empty token
    assert kv_key("thread", "cli", "x.") == "thread/cli/x"
    assert kv_key(".hidden", "a..b", "...") == "hidden/a.b/_"
    for key in (kv_key("thread", "cli", "x."), kv_key(".a..", "b")):
        assert not key.startswith(".") and not key.endswith(".") and ".." not in key


async def test_nats_bus_connect_is_idempotent(monkeypatch):
    import nats

    calls = []

    async def fake_connect(url, **kwargs):
        calls.append(url)
        return SimpleNamespace()

    monkeypatch.setattr(nats, "connect", fake_connect)
    bus = NatsBus("nats://example:4222")
    await bus.connect()
    await bus.connect()  # entrypoints connect for the KV, then the service's start() connects again
    assert calls == ["nats://example:4222"]


def test_validation_message_names_the_field_or_the_root():
    class M(BaseModel):
        n: int

    try:
        M(n="x")
    except ValidationError as e:
        assert validation_message(e).startswith("n: Input should be a valid integer")
    try:
        M.model_validate("not a dict")
    except ValidationError as e:
        assert validation_message(e, "input").startswith("input: ")


async def test_in_memory_kv_round_trip_and_isolation():
    kv = InMemoryKV()
    assert await kv.get("missing") is None
    value = {"turns": [{"role": "user", "text": "hi"}]}
    await kv.put("thread/cli/1", value)
    value["turns"].append({"role": "assistant", "text": "mutated after put"})
    got = await kv.get("thread/cli/1")
    assert got == {"turns": [{"role": "user", "text": "hi"}]}  # stored a copy
    got["turns"].clear()
    assert await kv.get("thread/cli/1") == {"turns": [{"role": "user", "text": "hi"}]}  # returned a copy
    await kv.put("thread/telegram/9", {"turns": []})
    assert await kv.keys("thread/cli") == ["thread/cli/1"]
    assert await kv.keys() == ["thread/cli/1", "thread/telegram/9"]
    await kv.delete("thread/cli/1")
    await kv.delete("thread/cli/1")  # idempotent
    assert await kv.get("thread/cli/1") is None


def test_new_id_is_time_ordered_and_unique():
    ids = [new_id() for _ in range(50)]
    assert len(set(ids)) == 50
    assert all(re.fullmatch(r"[0-9a-f]{21}", i) for i in ids)
    assert ids[0][:13] <= ids[-1][:13]  # millisecond prefix never goes backwards


def test_envelope_root_and_children():
    root = Envelope(source="telegram")
    assert root.cause is None and root.hops == 0 and root.ts.endswith("+00:00")
    child = root.child("main")
    assert child.cause == root.id and child.hops == 1 and child.source == "main"
    assert Envelope.child_of(child, "main").hops == 2
    # from an incoming payload, with or without an envelope
    from_dict = Envelope.child_of({"id": "abc", "hops": 3, "text": "hi"}, "main")
    assert from_dict.cause == "abc" and from_dict.hops == 4
    assert Envelope.child_of({"text": "no envelope"}, "x").cause is None


def test_envelope_is_frozen_and_validated():
    env = Envelope(source="main")
    with pytest.raises(ValidationError):
        env.source = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Envelope(source="main", hops=-1)


def test_stamp_is_the_json_object_for_the_bus():
    env = Envelope(source="cli", cause="p1", hops=1)
    data = env.stamp(channel="cli", thread="t", text="hi")
    assert data == {
        "id": env.id,
        "ts": env.ts,
        "source": "cli",
        "cause": "p1",
        "hops": 1,
        "channel": "cli",
        "thread": "t",
        "text": "hi",
    }
    json.dumps(data)  # plain JSON, nothing pydantic left in it


def test_into_builds_a_typed_message_from_an_envelope():
    class Say(Envelope):
        source: str = "main"
        text: str

    parent = Envelope(source="telegram").stamp(text="hi")
    say = Envelope.child_of(parent, "main").into(Say, text="reply")
    assert isinstance(say, Say) and say.cause == parent["id"] and say.hops == 1 and say.text == "reply"
    with pytest.raises(ValidationError):
        Envelope(source="main").into(Say)  # text is required


async def test_bus_accepts_pydantic_models_directly():
    bus = InMemoryBus()
    seen = []

    async def h(msg):
        seen.append(msg.data)

    await bus.subscribe("trace.x", h)
    env = Envelope(source="gateway")
    await bus.publish("trace.x", env)
    assert seen == [env.model_dump(mode="json")] and bus.published[0][1]["source"] == "gateway"


def test_input_schema_inlines_nested_models_and_trims():
    from typing import Literal

    from pydantic import Field

    from mycelium_sdk import input_schema

    class Item(BaseModel):
        name: str = Field(description="slug")
        kind: Literal["a", "b"] | None = None

    class Digest(BaseModel):
        summary: str
        items: list[Item] = Field(default_factory=list)
        main: Item | None = None

    schema = input_schema(Digest)
    assert "$defs" not in schema and "$ref" not in json.dumps(schema) and "title" not in json.dumps(schema)
    item = schema["properties"]["items"]["items"]
    assert item["type"] == "object" and item["required"] == ["name"]
    assert item["properties"]["kind"] == {"enum": ["a", "b"], "type": "string"}
    assert schema["properties"]["main"]["properties"]["name"] == {"description": "slug", "type": "string"}
    assert schema["required"] == ["summary"]
