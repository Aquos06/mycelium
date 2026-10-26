"""FastAPI application: the /api/v1 surface, the token gate, CORS, the error envelope, /healthz.

Route handlers live in the domain routers (`<domain>/router.py`), aggregated by api/router.py. This module
owns only the cross-cutting concerns. Add an endpoint to its domain, never here.

Two checks, default-deny on everything under /api/v1 (the socket makes the same two in events/router.py,
since the HTTP middleware never sees a websocket handshake): the browser's Origin must be one the app is
served from or this host, whether or not a token is set, and the token (WEB_TOKEN) must match when one is.
Unset, the gateway is open to the origins it knows, which is only right on a LAN behind Caddy or Tailscale.
/healthz and / stay outside the gate: docker's healthcheck and a load balancer only need a yes.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException  # the base: the router's own 404 is one of these, fastapi's subclass it

from ..service import WebGateway
from ..settings import WebSettings
from .deps import authorized, bearer_from_header, origin_allowed
from .router import PREFIX, api_router
from .schemas import ErrorResponse

GATE = PREFIX + "/"
log = logging.getLogger("mycelium.web")


def refusal(status: int, error: str) -> JSONResponse:
    return JSONResponse(ErrorResponse(error=error).model_dump(), status_code=status)


def create_app(gw: WebGateway, settings: WebSettings) -> FastAPI:
    """The app owns the gateway's life: the bus connects and subscribes on startup, closes on shutdown. That is
    what lets uvicorn's reloader (`make -C services dev`) and the test client start it the same way."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await gw.start()
        log.info(
            "web ready: auth=%s origins=%s",
            "token" if settings.token else "open (set WEB_TOKEN outside a trusted LAN)",
            ",".join(settings.cors_origins),
        )
        yield
        await gw.bus.close()

    app = FastAPI(
        title="mycelium web gateway", version="1", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.gateway = gw
    app.state.settings = settings
    app.include_router(api_router)

    @app.middleware("http")
    async def gate(request: Request, call_next):
        """Default deny under /api/v1/: the browser's origin first (CORS alone does not stop a `no-cors` POST from
        a page elsewhere), then the token."""
        if request.url.path.startswith(GATE):
            if not origin_allowed(settings, request.headers.get("origin"), request.headers.get("host")):
                return refusal(403, "this origin is not one the app is served from (WEB_CORS_ORIGINS)")
            if not authorized(settings, bearer_from_header(request.headers.get("authorization", ""))):
                return refusal(401, "a bearer token is required (WEB_TOKEN)")
        return await call_next(request)

    # Added last, so it is outermost: a 401 from the gate must still carry the CORS headers, or the browser
    # reports a network error instead of the refusal the app knows how to show.
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"], max_age=600
    )

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, e: RequestValidationError) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'] if p != 'body') or 'request'}: {err['msg']}" for err in e.errors()
        )
        return refusal(422, detail)

    @app.exception_handler(HTTPException)
    async def _http(_request: Request, e: HTTPException) -> JSONResponse:
        return refusal(e.status_code, str(e.detail))

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str | bool]:
        return {
            "ok": True,
            "service": "mycelium web gateway",
            "api": PREFIX,
            "app": "frontend/ (pnpm dev, or the frontend image)",
        }

    return app
