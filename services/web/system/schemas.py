"""The system domain's replies."""

from __future__ import annotations

from typing import Literal

from ..schemas import CHANNEL, WebSchema


class Health(WebSchema):
    ok: Literal[True] = True
    name: str  # whose assistant this is (WEB_USER_NAME): the app greets by it
    channel: str = CHANNEL
    version: str
    events: int  # buffered
    clients: int  # sockets open
    auth: bool  # a token is required
