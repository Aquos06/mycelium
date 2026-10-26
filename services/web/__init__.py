"""The web gateway (ARCHITECTURE §10): the bus for the browser.

The app in frontend/ talks only to this service: REST under /api/v1 for request/reply and for what it says,
one websocket for everything the bus says back. It is a channel like telegram (channel "web"): a message
typed in the app becomes `sense.chat`, Main's `out.say` / `out.ask` come back on the socket.

One package per domain, a router that only routes, the body in service.py:

__main__.py        `python -m web` in the container; `app()` is the uvicorn factory `make -C services dev` reloads
settings.py        WEB_PORT, WEB_TOKEN, WEB_USER_NAME, WEB_EVENT_BUFFER, WEB_RPC_TIMEOUT, WEB_CORS_ORIGINS
schemas.py         WebSchema, the base every payload here derives from, and the channel name
service.py         WebGateway: bus subscriptions, the recent-events buffer, chat, feedback, rpc
api/server.py      the FastAPI app: CORS, the token gate, the error envelope, /healthz
api/router.py      every domain router mounted under /api/v1; prefixes and tags live here
chat/              POST /chat, POST /feedback
events/            GET /events, WS /events/ws
rpc/               POST /rpc/{subject}
system/            GET /system/health
"""
