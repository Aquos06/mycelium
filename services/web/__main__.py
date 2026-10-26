"""Entrypoint: `python -m web` (the container), or `uvicorn --factory web.__main__:app --reload` for a hot
loop on the host (`make -C services dev`). The environment is read and validated by WebSettings (settings.py).
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from mycelium_sdk import NatsBus

from .api.server import create_app
from .service import WebGateway
from .settings import WebSettings


def app() -> FastAPI:
    """ASGI factory. The gateway starts in the app's lifespan (api/server.py), so uvicorn owns the whole life."""
    s = WebSettings()
    logging.basicConfig(level=s.log_level)
    bus = NatsBus(s.nats_url, name="web")
    return create_app(WebGateway(bus, buffer=s.buffer, rpc_timeout=s.rpc_timeout), s)


def main() -> None:
    application = app()
    s: WebSettings = application.state.settings
    # the numeric level: uvicorn knows only its own five names, ServiceSettings accepts every one logging does (WARN, FATAL)
    level = logging.getLevelNamesMapping()[s.log_level]
    uvicorn.run(application, host="0.0.0.0", port=s.port, log_level=level, access_log=False)


if __name__ == "__main__":
    main()
