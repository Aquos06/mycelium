"""Entrypoint: python -m main. The environment is read and validated by MainSettings (settings.py)."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime
from zoneinfo import ZoneInfo

from mycelium_sdk import NatsBus, NatsKV

from .service import MainService
from .settings import MainSettings
from .thread import ThreadStore

log = logging.getLogger("mycelium.main")


async def main() -> None:
    s = MainSettings()
    logging.basicConfig(level=s.log_level)
    zone = ZoneInfo(s.tz)
    bus = NatsBus(s.nats_url, name="main")
    await bus.connect()
    kv = await NatsKV(bus.nc, "main").open()
    store = ThreadStore(kv, max_turns=s.max_turns)
    service = MainService(bus, store, today=lambda: datetime.now(zone).date(), tz=s.tz, llm_timeout=s.llm_timeout)
    await service.start()
    log.info("main ready: tz=%s llm_timeout=%ss", s.tz, s.llm_timeout)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await service.drain()
    await bus.close()


if __name__ == "__main__":
    asyncio.run(main())
