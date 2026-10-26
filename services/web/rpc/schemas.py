"""The rpc domain's request body. The reply has no model here: it is whatever the responder answers."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..schemas import WebSchema


class RpcIn(WebSchema):
    payload: dict[str, Any] = Field(default_factory=dict)  # the responder's own request shape
    timeout: float | None = Field(default=None, gt=0, le=600)
