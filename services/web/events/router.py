"""Routing only: the page comes from WebGateway.events, the socket drains one of its client queues.

The socket checks its own door: the HTTP gate in api/server.py never sees a websocket handshake. The origin
first (a page from elsewhere is refused whether or not a token is set), then the token, which the app offers
as the `bearer` subprotocol (api/deps.py) so it stays out of URLs and access logs; `?token=` is kept for
clients that cannot set a header. Both refusals happen AFTER accept, with an application close code: a close
before accept is an HTTP 403 on the handshake, which a browser reports as 1006 and the app cannot tell apart
from the gateway being down.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..api.deps import WS_BEARER, Gateway, Settings, authorized, bearer_from_subprotocols, origin_allowed
from .schemas import EventsPage, Frame, Hello

router = APIRouter()

WS_UNAUTHORIZED = 4401  # application close code: the token was missing or wrong
WS_FORBIDDEN = 4403  # the page's origin is not one the app is served from (WEB_CORS_ORIGINS)
WS_TOO_SLOW = 1013  # the browser stopped reading; it reconnects and fetches the gap


@router.get("", response_model=EventsPage, summary="the recent bus events, oldest first")
async def events(
    gw: Gateway,
    limit: int = Query(default=200, ge=1, le=5000),
    after: int = Query(default=0, ge=0, description="a seq: only events after it"),
) -> EventsPage:
    return EventsPage(seq=gw.seq, events=gw.events(limit, after))


@router.websocket("/ws")
async def stream(socket: WebSocket, gw: Gateway, settings: Settings, token: str | None = Query(default=None)) -> None:
    offered = socket.headers.get("sec-websocket-protocol")
    # a browser that offered subprotocols fails the connection unless one is chosen; `bearer` is the only one known
    await socket.accept(subprotocol=WS_BEARER if offered else None)
    if not origin_allowed(settings, socket.headers.get("origin"), socket.headers.get("host")):
        await socket.close(code=WS_FORBIDDEN)
        return
    if not authorized(settings, bearer_from_subprotocols(offered) or token):
        await socket.close(code=WS_UNAUTHORIZED)
        return
    q = gw.attach()

    async def reader() -> None:  # the app sends nothing the gateway acts on; reading is how a close is seen
        while True:
            await socket.receive_text()

    reading = asyncio.create_task(reader())
    try:
        await socket.send_json(Hello(seq=gw.seq, name=settings.user_name).model_dump())
        while True:
            getting = asyncio.create_task(q.get())
            done, _ = await asyncio.wait({getting, reading}, return_when=asyncio.FIRST_COMPLETED)
            if reading in done:
                getting.cancel()
                break
            ev = getting.result()
            if ev is None:
                await socket.close(code=WS_TOO_SLOW)
                break
            await socket.send_json(
                Frame(seq=ev.seq, subject=ev.subject, data=ev.data, received=ev.received).model_dump()
            )
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        gw.detach(q)
        reading.cancel()
        if reading.done() and not reading.cancelled():
            reading.exception()  # a disconnect raised in the reader: seen, not logged as unretrieved
