"""The web gateway's body, no HTTP: settings, the buffer, what chat and feedback put on the bus, the rpc guard.

The endpoints are covered one by one in test_web_api.py.
"""

import pytest

from mycelium_sdk import InMemoryBus
from web.api.deps import authorized
from web.chat.schemas import ChatIn, FeedbackIn
from web.rpc.schemas import RpcIn
from web.service import RPC_RE, WebGateway
from web.settings import DEV_ORIGINS, WebSettings


async def _gateway(buffer=300):
    gw = WebGateway(InMemoryBus(), buffer=buffer, rpc_timeout=0.2)
    await gw.start()
    return gw


def test_settings_read_the_environment_and_an_empty_token_means_open():
    s = WebSettings.model_validate({"WEB_PORT": "9000", "WEB_TOKEN": "  ", "WEB_USER_NAME": "Mei"})
    assert s.port == 9000 and s.token is None and s.user_name == "Mei" and s.buffer == 300
    assert s.cors_origins == DEV_ORIGINS
    assert WebSettings.model_validate({"WEB_TOKEN": "s3cret"}).token == "s3cret"
    with pytest.raises(ValueError):
        WebSettings.model_validate({"WEB_EVENT_BUFFER": "2"})


def test_cors_origins_come_as_a_comma_list_from_the_environment_too(monkeypatch):
    s = WebSettings.model_validate({"WEB_CORS_ORIGINS": "https://m.example.com, http://localhost:3000,"})
    assert s.cors_origins == ["https://m.example.com", "http://localhost:3000"]
    assert WebSettings.model_validate({"WEB_CORS_ORIGINS": ""}).cors_origins == []
    # the real path: the env source, which must not try to JSON-decode the comma list (it did, and the container crashed)
    monkeypatch.setenv("WEB_CORS_ORIGINS", "http://a.example,http://b.example")
    assert WebSettings().cors_origins == ["http://a.example", "http://b.example"]


def test_authorized_is_open_without_a_token_and_exact_with_one():
    assert authorized(WebSettings.model_validate({}), None)
    locked = WebSettings.model_validate({"WEB_TOKEN": "s3cret"})
    assert authorized(locked, "s3cret")
    assert not authorized(locked, "s3cre") and not authorized(locked, None) and not authorized(locked, "")


def test_request_bodies_forbid_unknown_fields_and_feedback_needs_an_answer_or_a_vote():
    assert ChatIn(text="hi").thread == "web"
    with pytest.raises(ValueError, match="extra"):
        ChatIn(text="hi", channel="telegram")
    with pytest.raises(ValueError, match="an answer or a vote"):
        FeedbackIn(ref="x")
    assert FeedbackIn(ref="x", vote=-1).answer is None
    with pytest.raises(ValueError):
        FeedbackIn(ref="x", vote=2)
    assert RpcIn().payload == {} and RpcIn(payload={"a": 1}, timeout=2).timeout == 2


def test_the_rpc_subject_pattern_admits_only_rpc_subjects():
    assert RPC_RE.match("rpc.sys.list") and RPC_RE.match("rpc.mod.hello.stats") and RPC_RE.match("rpc.memory.recall")
    for bad in ("sense.chat", "rpc.sys", "rpc..list", "rpc.sys.list.", "rpc.sys.li st", ""):
        assert not RPC_RE.match(bad), bad


async def test_chat_and_feedback_go_on_the_bus_as_the_web_channel():
    gw = await _gateway()
    sent = await gw.chat(ChatIn(text="dinner 350"))
    [(subject, data)] = gw.bus.events("sense.chat")
    assert subject == "sense.chat" and sent.ok is True
    assert data["id"] == sent.id and data["source"] == "web" and data["channel"] == "web"
    assert data["thread"] == "web" and data["text"] == "dinner 350" and data["cause"] is None

    await gw.feedback(FeedbackIn(ref="ask1", thread="t2", answer="9pm"))
    await gw.feedback(FeedbackIn(ref="say1", vote=1))
    answers = [d for _, d in gw.bus.events("sense.feedback")]
    assert answers[0]["ref"] == "ask1" and answers[0]["answer"] == "9pm" and answers[0]["thread"] == "t2"
    assert "vote" not in answers[0] and answers[1]["vote"] == 1 and "answer" not in answers[1]


async def test_the_buffer_keeps_events_in_order_and_serves_a_cursor():
    gw = await _gateway(buffer=10)
    for i in range(12):
        await gw.bus.publish("mod.hello.message.counted", {"count": i})
    assert gw.seq == 12 and len(gw.recent) == 10
    assert [e.data["count"] for e in gw.events()] == list(range(2, 12))
    assert [e.seq for e in gw.events(limit=3)] == [10, 11, 12]
    assert [e.seq for e in gw.events(after=10)] == [11, 12]
    assert gw.events()[0].subject == "mod.hello.message.counted" and gw.events()[0].received.endswith("+00:00")


async def test_rpc_refuses_a_non_rpc_subject_before_touching_the_bus_and_times_out_on_silence():
    gw = await _gateway()
    with pytest.raises(ValueError, match="not an rpc subject"):
        await gw.rpc("sense.chat", RpcIn(payload={"text": "x"}))
    assert gw.bus.events("sense.chat") == []
    with pytest.raises(TimeoutError):
        await gw.rpc("rpc.nobody.home", RpcIn())


async def test_a_socket_that_stops_reading_is_dropped_with_a_none():
    gw = await _gateway()
    q = gw.attach()
    assert gw.clients == 1
    from web.service import CLIENT_QUEUE

    for i in range(CLIENT_QUEUE + 1):
        await gw.bus.publish("sys.tick", {"i": i})
    assert gw.clients == 0
    drained = []
    while not q.empty():
        drained.append(q.get_nowait())
    assert len(drained) == CLIENT_QUEUE + 1 and drained[-1] is None
