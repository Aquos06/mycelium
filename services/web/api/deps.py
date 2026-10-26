"""Shared dependencies: the one WebGateway and the settings, built in __main__ and kept on app.state, and the
two checks every door makes: the token, and where the browser came from.

Typed `Annotated` aliases keep the route signatures short: `gw: Gateway`, `settings: Settings`. They read
through `HTTPConnection`, the base of both Request and WebSocket, so the socket route can use them too.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends
from starlette.requests import HTTPConnection

from ..service import WebGateway
from ..settings import WebSettings

#: The websocket subprotocol the app offers to carry its token: `Sec-WebSocket-Protocol: bearer, <base64url token>`.
#: The one header a browser lets a WebSocket set, so the token stays out of URLs and the access logs in front.
WS_BEARER = "bearer"


def get_gateway(conn: HTTPConnection) -> WebGateway:
    return conn.app.state.gateway


def get_settings(conn: HTTPConnection) -> WebSettings:
    return conn.app.state.settings


Gateway = Annotated[WebGateway, Depends(get_gateway)]
Settings = Annotated[WebSettings, Depends(get_settings)]


def authorized(settings: WebSettings, token: str | None) -> bool:
    """No token configured: open. Otherwise a constant-time match against WEB_TOKEN."""
    if settings.token is None:
        return True
    return token is not None and secrets.compare_digest(token.encode(), settings.token.encode())


def origin_allowed(settings: WebSettings, origin: str | None, host: str | None) -> bool:
    """Where a browser request came from, checked even when the gateway is open.

    CORS only hides responses; it never stops a websocket handshake or a `no-cors` POST, so without this any
    page the user visits could read the bus and fire rpc.* side effects. No Origin header means no browser
    cross-site request (curl, the tests, a same-origin GET): allowed. Otherwise the origin must be one the app
    is served from (WEB_CORS_ORIGINS) or this very host, the same-origin deployment behind Caddy, where only
    the host can be compared because Caddy terminates TLS and the scheme differs.
    """
    if origin is None:
        return True
    if origin in settings.cors_origins:
        return True
    try:
        origin_host = urlsplit(origin).netloc.lower()
    except ValueError:
        return False
    return bool(origin_host) and host is not None and origin_host == host.lower()


def bearer_from_header(header: str) -> str | None:
    """The token out of `Authorization: Bearer <token>`, or None."""
    return header[7:] if header.lower().startswith("bearer ") else None


def bearer_from_subprotocols(header: str | None) -> str | None:
    """The token the app offered as a websocket subprotocol: `bearer, <base64url>`. None when it offered none."""
    if not header:
        return None
    offered = [p.strip() for p in header.split(",")]
    if len(offered) < 2 or offered[0] != WS_BEARER:
        return None
    encoded = offered[1]
    try:
        return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
