"""Entrypoint: python -m main

Env:
    NATS_URL            nats://nats:4222
    MAIN_TZ             Asia/Taipei      (what "today" means in the prompt)
    MAIN_MAX_TURNS      20               (thread turns kept in KV)
    MAIN_LLM_TIMEOUT    90               (seconds per planner round; raise it for a cold local model)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import datetime
from zoneinfo import ZoneInfo

from mycelium_sdk import NatsBus, NatsKV

from .service import MainService
from .thread import ThreadStore

log = logging.getLogger("mycelium.main")


async def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    tz = os.environ.get("MAIN_TZ", "Asia/Taipei")
    zone = ZoneInfo(tz)
    bus = NatsBus(os.environ.get("NATS_URL", "nats://nats:4222"), name="main")
    await bus.connect()
    kv = await NatsKV(bus.nc, "main").open()
    store = ThreadStore(kv, max_turns=int(os.environ.get("MAIN_MAX_TURNS", "20")))
    service = MainService(
        bus,
        store,
        today=lambda: datetime.now(zone).date(),
        tz=tz,
        llm_timeout=float(os.environ.get("MAIN_LLM_TIMEOUT", "90")),
    )
    await service.start()
    log.info("main ready: tz=%s llm_timeout=%ss", tz, service.llm_timeout)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await service.drain()
    await bus.close()


if __name__ == "__main__":
    asyncio.run(main())
