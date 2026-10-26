"""Routing only: WebGateway.rpc validates the subject and does the request."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..api.deps import Gateway
from .schemas import RpcIn

router = APIRouter()


@router.post(
    "/{subject}",
    response_model=dict[str, Any],
    summary="request/reply on an rpc.* subject; the body is the responder's own reply, {ok: false, error} included",
)
async def rpc(subject: str, gw: Gateway, req: RpcIn | None = None) -> dict[str, Any]:
    req = req or RpcIn()
    try:
        return await gw.rpc(subject, req)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except TimeoutError:
        raise HTTPException(504, f"no reply from {subject} within {req.timeout or gw.rpc_timeout:g}s") from None
