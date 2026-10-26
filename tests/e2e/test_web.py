"""End to end against the running docker compose stack: the web gateway answers its API, the frontend
serves the app, and a message typed in the app reaches Main and comes back as out.say on channel web.

    docker compose up -d --build
    NATS_URL=nats://localhost:4222 WEB_URL=http://localhost:8080 FRONTEND_URL=http://localhost:3000 \\
        pytest -m e2e tests/e2e/test_web.py
"""

import os
import uuid

import httpx
import pytest

from tests.conftest import needs_nats
from tests.e2e.test_stack import wait_for

WEB_URL = os.environ.get("WEB_URL", f"http://localhost:{os.environ.get('WEB_PORT', '8080')}")
FRONTEND_URL = os.environ.get("FRONTEND_URL", f"http://localhost:{os.environ.get('FRONTEND_PORT', '3000')}")
API = "/api/v1"

pytestmark = [pytest.mark.e2e, needs_nats]


async def test_web_gateway_answers_its_api_and_bridges_a_chat_turn():
    async with httpx.AsyncClient(base_url=WEB_URL, timeout=10) as http:

        async def up():
            r = await http.get(f"{API}/system/health")
            return r if r.status_code == 200 and r.json()["ok"] else None

        health = (await wait_for(up, timeout=120)).json()
        assert health["channel"] == "web" and health["name"] and health["version"]

        root = (await http.get("/")).json()
        assert root["ok"] is True and root["api"] == API  # the gateway alone: the app is the frontend service

        listed = (await http.post(f"{API}/rpc/rpc.sys.list")).json()
        assert listed["ok"] is True and isinstance(listed["modules"], list)

        bad = await http.post(f"{API}/rpc/sense.chat", json={"payload": {"text": "nope"}})
        assert bad.status_code == 400 and bad.json() == {"ok": False, "error": "not an rpc subject: 'sense.chat'"}

        pre = await http.options(
            f"{API}/chat",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
        )
        assert pre.headers.get("access-control-allow-origin") == "http://localhost:3000"

        marker = uuid.uuid4().hex[:8]
        thread = f"e2e-{marker}"
        sent = (
            await http.post(f"{API}/chat", json={"text": f"hello from the web e2e {marker}", "thread": thread})
        ).json()
        assert sent["ok"] is True and sent["thread"] == thread

        async def replied():
            events = (await http.get(f"{API}/events", params={"limit": 300})).json()["events"]
            mine = [e for e in events if e["data"].get("channel") == "web" and e["data"].get("thread") == thread]
            subjects = {e["subject"] for e in mine}
            return mine if {"sense.chat", "out.say"} <= subjects else None

        mine = await wait_for(
            replied, timeout=150
        )  # without a model key Main still answers: it says it cannot reach one
        chat = next(e for e in mine if e["subject"] == "sense.chat")
        say = next(e for e in mine if e["subject"] == "out.say")
        assert chat["data"]["id"] == sent["id"] and chat["data"]["source"] == "web"
        assert say["data"]["cause"] == sent["id"] and say["data"]["text"]
        assert any(e["subject"] == "trace.plan" and e["data"]["reply_id"] == say["data"]["id"] for e in mine)


async def test_frontend_serves_the_app():
    async with httpx.AsyncClient(base_url=FRONTEND_URL, timeout=10, follow_redirects=True) as http:

        async def up():
            r = await http.get("/login")
            return r if r.status_code == 200 else None

        login = await wait_for(up, timeout=180)  # the image's first start
        assert "<title>mycelium" in login.text and "token" in login.text.lower()
        home = await http.get("/")
        assert home.status_code == 200 and "mycelium" in home.text
        assert (await http.get("/manifest.webmanifest")).json()["name"] == "mycelium"
        assert (await http.get("/settings")).url.path == "/settings/models"
        assert (await http.get("/nothing/here")).status_code == 404
