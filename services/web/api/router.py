"""Every domain router mounted under /api/v1. Prefixes and tags are declared here, not in the domains,
so this file is the one place the whole URL surface can be read:

    POST /api/v1/chat              say something to Main
    POST /api/v1/chat/feedback     answer an out.ask, vote on an out.say
    GET  /api/v1/events            the recent bus events
    WS   /api/v1/events/ws         every new bus event
    POST /api/v1/rpc/{subject}     request/reply on any rpc.* subject
    GET  /api/v1/system/health     the gateway's state (and the app's login check)

`responses` documents the refusal envelope once for the whole surface.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..chat.router import router as chat_router
from ..events.router import router as events_router
from ..rpc.router import router as rpc_router
from ..system.router import router as system_router
from .schemas import ErrorResponse

PREFIX = "/api/v1"

api_router = APIRouter(
    prefix=PREFIX,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)

api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(events_router, prefix="/events", tags=["events"])
api_router.include_router(rpc_router, prefix="/rpc", tags=["rpc"])
api_router.include_router(system_router, prefix="/system", tags=["system"])
