"""One test per endpoint of the web gateway, through FastAPI's test client over an in-memory bus.

These are integration tests in the sense of the house rule (every endpoint wired, no HTTP mocked) and
unit tests in this repo's sense (no NATS, no Postgres), so they run in the fast gate.
"""

import base64
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mycelium_sdk import InMemoryBus, validate_manifest
from web.api.server import create_app
from web.events.router import WS_FORBIDDEN, WS_UNAUTHORIZED
from web.service import WebGateway
from web.settings import WebSettings

API = "/api/v1"
APP = "http://localhost:3000"  # the app's origin, in the default WEB_CORS_ORIGINS


def _settings(**env):
    return WebSettings.model_validate(env)


@contextmanager
def _client(settings=None, rpc_timeout=0.2):
    """The app entered exactly once; its lifespan starts the gateway (and closes the bus on the way out)."""
    bus = InMemoryBus()
    gw = WebGateway(bus, rpc_timeout=rpc_timeout)
    with TestClient(create_app(gw, settings or _settings())) as client:
        yield client, gw, bus


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def test_get_system_health_describes_the_gateway():
    with _client() as (client, gw, bus):
        r = client.get(f"{API}/system/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["name"] == "Hansen" and body["channel"] == "web"
        assert body["events"] == 0 and body["clients"] == 0 and body["auth"] is False
        assert body["version"].count(".") == 2


def test_the_lifespan_subscribes_once_and_closes_the_bus_after():
    bus = InMemoryBus()
    gw = WebGateway(bus)
    with TestClient(create_app(gw, _settings())) as client:
        client.portal.call(bus.publish, "sense.chat", {"text": "once"})
        assert gw.seq == 1  # one subscription per prefix, so one event is one event
        assert client.get(f"{API}/events").json()["seq"] == 1
    assert bus._subs == []  # the lifespan's shutdown closed the bus


def test_post_chat_publishes_sense_chat_and_answers_the_envelope_id():
    with _client() as (client, gw, bus):
        r = client.post(f"{API}/chat", json={"text": "hi there", "thread": "t1"})
        assert r.status_code == 200 and r.json()["ok"] is True and r.json()["thread"] == "t1"
        [(_, chat)] = bus.events("sense.chat")
        assert chat["id"] == r.json()["id"] and chat["text"] == "hi there" and chat["channel"] == "web"


def test_post_chat_refuses_an_empty_text_and_an_unknown_field_with_the_error_envelope():
    with _client() as (client, gw, bus):
        r = client.post(f"{API}/chat", json={"text": ""})
        assert r.status_code == 422 and r.json()["ok"] is False and r.json()["error"].startswith("text:")
        r = client.post(f"{API}/chat", json={"text": "hi", "channel": "telegram"})
        assert r.status_code == 422 and "channel" in r.json()["error"]
        assert bus.events("sense.chat") == []


def test_post_chat_feedback_publishes_sense_feedback():
    with _client() as (client, gw, bus):
        r = client.post(f"{API}/chat/feedback", json={"ref": "ask1", "thread": "t1", "answer": "9pm"})
        assert r.status_code == 200 and r.json()["ok"] is True
        r = client.post(f"{API}/chat/feedback", json={"ref": "say1", "vote": -1})
        assert r.status_code == 200
        r = client.post(f"{API}/chat/feedback", json={"ref": "say1"})
        assert r.status_code == 422 and "an answer or a vote" in r.json()["error"]
        [a, v] = [d for _, d in bus.events("sense.feedback")]
        assert a["answer"] == "9pm" and a["ref"] == "ask1" and v["vote"] == -1 and "answer" not in v


def test_get_events_pages_the_buffer_after_a_cursor():
    with _client() as (client, gw, bus):
        client.portal.call(bus.publish, "sense.chat", {"text": "earlier"})
        client.portal.call(bus.publish, "out.say", {"channel": "web", "thread": "web", "text": "hello back"})
        r = client.get(f"{API}/events")
        assert r.status_code == 200 and r.json()["ok"] is True and r.json()["seq"] == 2
        assert [e["subject"] for e in r.json()["events"]] == ["sense.chat", "out.say"]
        r = client.get(f"{API}/events", params={"after": 1})
        assert [e["seq"] for e in r.json()["events"]] == [2]
        r = client.get(f"{API}/events", params={"limit": 0})
        assert r.status_code == 422 and r.json()["error"].startswith("query.limit")


def test_the_socket_says_hello_then_streams_the_bus():
    with _client() as (client, gw, bus):
        client.portal.call(bus.publish, "sense.chat", {"text": "earlier"})
        with client.websocket_connect(f"{API}/events/ws") as ws:
            assert ws.receive_json() == {"type": "hello", "seq": 1, "name": "Hansen"}
            assert client.get(f"{API}/system/health").json()["clients"] == 1
            client.portal.call(bus.publish, "trace.plan", {"channel": "web", "thread": "web", "rounds": 1})
            frame = ws.receive_json()
            assert frame["type"] == "event" and frame["seq"] == 2 and frame["subject"] == "trace.plan"
            assert frame["data"]["rounds"] == 1 and frame["received"]
        assert client.get(f"{API}/system/health").json()["clients"] == 0


def test_post_rpc_forwards_the_request_and_returns_the_responders_reply_untouched():
    async def list_modules(msg):
        await msg.respond({"ok": True, "modules": [{"name": "hello", "status": "running"}], "echo": msg.data})

    with _client() as (client, gw, bus):
        client.portal.call(bus.subscribe, "rpc.sys.list", list_modules)
        r = client.post(f"{API}/rpc/rpc.sys.list", json={"payload": {"only": "running"}})
        assert r.status_code == 200 and r.json()["modules"][0]["name"] == "hello"
        assert r.json()["echo"] == {"only": "running"}
        r = client.post(f"{API}/rpc/rpc.sys.list")  # no body: an empty payload
        assert r.status_code == 200 and r.json()["ok"] and r.json()["echo"] == {}


def test_post_rpc_refuses_a_non_rpc_subject_and_reports_silence_as_504():
    with _client() as (client, gw, bus):
        r = client.post(f"{API}/rpc/sense.chat", json={"payload": {"text": "x"}})
        assert r.status_code == 400 and "not an rpc subject" in r.json()["error"]
        assert bus.events("sense.chat") == []
        r = client.post(f"{API}/rpc/rpc.nobody.home")
        assert r.status_code == 504 and r.json() == {"ok": False, "error": "no reply from rpc.nobody.home within 0.2s"}


# ---- a module's page: its views ------------------------------------------------------------------------------

SPENDING = {
    "name": "spending",
    "purpose": "Tracks spending, with totals by category.",
    "requests": {
        "summary": {
            "description": "Totals since a day, all time without one.",
            "params": {"from": "optional date"},
            "returns": {"total": "number", "count": "number", "by_category": "map"},
        },
        "add": {"description": "Store one expense.", "params": {"amount": "number"}, "returns": {"id": "number"}},
        "broken": {"description": "A request that refuses.", "returns": {"x": "number"}},
    },
}
SUMMARY = {"ok": True, "total": 3420, "count": 6, "by_category": {"food": 1820, "coffee": 740}}


def _module(client, bus, manifest, status="running"):
    """The supervisor's list and the module's own requests, as they answer on the bus; returns what was asked."""
    asked = []

    async def list_modules(msg):
        await msg.respond(
            {
                "ok": True,
                "modules": [
                    {
                        "name": manifest["name"],
                        "status": status,
                        "manifest": validate_manifest(manifest).model_dump(mode="json"),
                    }
                ],
            }
        )

    async def answer(msg):
        asked.append((msg.subject, msg.data))
        if msg.subject.endswith(".broken"):
            await msg.respond({"ok": False, "error": "database is locked"})
        else:
            await msg.respond(SUMMARY if msg.subject.endswith(".summary") else {"ok": True, "id": 1})

    client.portal.call(bus.subscribe, "rpc.sys.list", list_modules)
    for action in manifest["requests"]:
        client.portal.call(bus.subscribe, f"rpc.mod.{manifest['name']}.{action}", answer)
    return asked


def test_a_module_page_shows_each_declared_view_from_what_the_module_answers():
    views = {
        "week": {
            "title": "This week",
            "request": "summary",
            "args": {"from": "$week_start"},
            "show": "stats",
            "fields": [{"key": "total", "format": "money"}, "count"],
        },
        "by_category": {
            "title": "By category",
            "request": "summary",
            "args": {"from": "$week_start"},
            "path": "by_category",
            "show": "chart",
        },
        "sneaky": {"title": "Sneaky", "request": "add", "show": "stats"},
        "broken": {"title": "Broken", "request": "broken", "show": "stats"},
    }
    with _client() as (client, gw, bus):
        asked = _module(client, bus, {**SPENDING, "views": views})
        r = client.get(f"{API}/modules/spending/views")
        assert r.status_code == 200
        body = r.json()
        assert (body["running"], body["declared"]) == (True, True)
        got = {v["id"]: (v["block"]["kind"] if v["block"] else None, v["error"]) for v in body["views"]}
        assert got["week"] == ("stats", None) and got["by_category"] == ("chart", None)
        assert got["sneaky"] == (
            None,
            "view 'sneaky': 'add' changes data; a view only reads (a page that opens changes nothing)",
        )
        assert got["broken"] == (None, "spending.broken: database is locked")
        assert body["views"][0]["block"]["stats"][0] == {"label": "Total", "value": {"v": 3420.0, "s": "NT$3,420"}}
        # one ask for the two views of the same request and arguments; `add` never asked
        assert [s for s, _ in asked] == ["rpc.mod.spending.summary", "rpc.mod.spending.broken"]
        assert asked[0][1]["from"].count("-") == 2  # $week_start, as a date


def test_a_module_without_views_is_shown_from_its_readable_requests():
    with _client() as (client, gw, bus):
        asked = _module(client, bus, SPENDING)
        body = client.get(f"{API}/modules/spending/views").json()
        assert body["declared"] is False
        assert [(v["id"], v["title"], v["block"]["kind"] if v["block"] else v["error"]) for v in body["views"]] == [
            ("summary.0", "Summary", "stats"),
            ("summary.1", "By category", "chart"),
            ("broken", "broken", "spending.broken: database is locked"),
        ]
        assert "rpc.mod.spending.add" not in [s for s, _ in asked]


def test_a_module_page_that_cannot_be_shown_says_why():
    with _client() as (client, gw, bus):
        _module(client, bus, SPENDING, status="stopped")
        assert client.get(f"{API}/modules/spending/views").json() == {
            "name": "spending",
            "running": False,
            "declared": False,
            "views": [],
        }
        assert client.get(f"{API}/modules/nobody/views").status_code == 404
        assert client.get(f"{API}/modules/Not_A_Name/views").status_code == 400
    with _client() as (client, gw, bus):
        assert client.get(f"{API}/modules/spending/views").status_code == 504  # no supervisor on the bus


def test_the_token_gate_covers_every_api_route_and_the_socket_but_not_healthz():
    with _client(_settings(WEB_TOKEN="s3cret")) as (client, gw, bus):
        for method, path in (
            ("get", "/system/health"),
            ("get", "/events"),
            ("post", "/chat"),
            ("post", "/rpc/rpc.sys.list"),
            ("get", "/modules/hello/views"),
        ):
            r = getattr(client, method)(API + path)
            assert r.status_code == 401 and r.json() == {"ok": False, "error": "a bearer token is required (WEB_TOKEN)"}
        assert client.get(f"{API}/system/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
        r = client.get(f"{API}/system/health", headers={"Authorization": "Bearer s3cret"})
        assert r.status_code == 200 and r.json()["auth"] is True
        assert client.get("/healthz").json() == {"ok": True}
        assert client.get("/").json()["api"] == API


def test_the_socket_refuses_a_bad_token_after_accepting_so_the_browser_sees_4401():
    with _client(_settings(WEB_TOKEN="s3cret")) as (client, gw, bus):
        for connect in (
            lambda: client.websocket_connect(f"{API}/events/ws"),
            lambda: client.websocket_connect(f"{API}/events/ws?token=wrong"),
            lambda: client.websocket_connect(f"{API}/events/ws", subprotocols=["bearer", _b64url("wrong")]),
            lambda: client.websocket_connect(f"{API}/events/ws", subprotocols=["other"]),
        ):
            with connect() as ws, pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == WS_UNAUTHORIZED
        assert client.get(f"{API}/system/health", headers={"Authorization": "Bearer s3cret"}).json()["clients"] == 0


def test_the_socket_takes_the_token_as_the_bearer_subprotocol_or_a_query_parameter():
    with _client(_settings(WEB_TOKEN="s3cret")) as (client, gw, bus):
        with client.websocket_connect(f"{API}/events/ws", subprotocols=["bearer", _b64url("s3cret")]) as ws:
            assert ws.accepted_subprotocol == "bearer"
            assert ws.receive_json()["type"] == "hello"
        with client.websocket_connect(f"{API}/events/ws?token=s3cret") as ws:
            assert ws.receive_json()["type"] == "hello"


def test_a_page_from_elsewhere_is_refused_even_when_the_gateway_is_open():
    with _client() as (client, gw, bus):
        evil = {"Origin": "http://evil.example"}
        # the attack CORS does not stop: a no-cors POST with a Blob body, no Content-Type, no preflight
        r = client.post(f"{API}/rpc/rpc.sys.stop", content=b'{"payload": {"name": "hello"}}', headers=evil)
        assert r.status_code == 403 and r.json()["ok"] is False and "WEB_CORS_ORIGINS" in r.json()["error"]
        assert client.get(f"{API}/events", headers=evil).status_code == 403
        with (
            client.websocket_connect(f"{API}/events/ws", headers=evil) as ws,
            pytest.raises(WebSocketDisconnect) as closed,
        ):
            ws.receive_json()
        assert closed.value.code == WS_FORBIDDEN
        # the app's own origin, the same host (Caddy in front, any scheme), and no Origin at all (curl) are fine
        assert client.get(f"{API}/events", headers={"Origin": APP}).status_code == 200
        assert (
            client.get(f"{API}/events", headers={"Origin": "https://testserver", "Host": "testserver"}).status_code
            == 200
        )
        assert client.get(f"{API}/events").status_code == 200
        with client.websocket_connect(f"{API}/events/ws", headers={"Origin": APP}) as ws:
            assert ws.receive_json()["type"] == "hello"


def test_cors_lets_the_app_origin_in_and_answers_a_refusal_with_the_headers_too():
    with _client(_settings(WEB_TOKEN="s3cret", WEB_CORS_ORIGINS=APP)) as (client, gw, bus):
        r = client.options(
            f"{API}/chat",
            headers={
                "Origin": APP,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == APP
        r = client.get(f"{API}/system/health", headers={"Origin": APP})
        assert r.status_code == 401 and r.headers["access-control-allow-origin"] == APP
        r = client.get(f"{API}/system/health", headers={"Origin": "http://evil.example"})
        assert r.status_code == 403 and "access-control-allow-origin" not in r.headers


def test_unknown_routes_answer_the_error_envelope():
    with _client() as (client, gw, bus):
        r = client.get(f"{API}/nope")
        assert r.status_code == 404 and r.json() == {"ok": False, "error": "Not Found"}
        assert client.get("/anything").status_code == 404


def test_the_socket_forwards_stream_frames_live_and_the_buffer_never_keeps_them():
    with _client() as (client, gw, bus):
        with client.websocket_connect(f"{API}/events/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            delta = {
                "cause": "m1",
                "request": "r1",
                "slot": "planner",
                "provider": "claude",
                "seq": 1,
                "text": "Hel",
                "done": False,
            }
            client.portal.call(bus.publish, "stream.llm", delta)
            frame = ws.receive_json()
            assert frame == {"type": "stream", "subject": "stream.llm", "data": delta}
            client.portal.call(bus.publish, "out.say", {"channel": "web", "thread": "web", "text": "Hello"})
            assert ws.receive_json()["type"] == "event"
        page = client.get(f"{API}/events").json()
        assert page["seq"] == 1 and [e["subject"] for e in page["events"]] == ["out.say"]  # the stream left no trace
