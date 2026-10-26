"""The one refusal envelope, documented once on the aggregator and returned by every handler in server.py.

{"ok": false, "error": "..."} is the shape every bus reply already uses, so the app reads one shape
whether a refusal came from this gateway or from the service that answered an rpc.
"""

from __future__ import annotations

from typing import Literal

from ..schemas import WebSchema


class ErrorResponse(WebSchema):
    ok: Literal[False] = False
    error: str
