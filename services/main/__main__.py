"""Entrypoint: python -m main. The environment is read and validated by MainSettings (settings.py)."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime
from zoneinfo import ZoneInfo

from mycelium_sdk import NatsBus, NatsKV

from .service import MainService
from .settings import MainSettings, quiet_hours
from .thread import ThreadStore
from .wake import WakePolicy

log = logging.getLogger("mycelium.main")


async def main() -> None:
    s = MainSettings()
    logging.basicConfig(level=s.log_level)
    zone = ZoneInfo(s.tz)
    bus = NatsBus(s.nats_url, name="main")
    await bus.connect()
    kv = await NatsKV(bus.nc, "main").open()
    store = ThreadStore(kv, max_turns=s.max_turns)
    service = MainService(
        bus,
        store,
        today=lambda: datetime.now(zone).date(),
        tz=s.tz,
        llm_timeout=s.llm_timeout,
        currency=s.currency.upper(),
        wake=WakePolicy(
            every_s=s.wake_every * 60,
            quiet=quiet_hours(s.quiet_hours),
            budget=s.wake_budget,
            channels=tuple(c.strip() for c in s.wake_channels.split(",") if c.strip()),
        ),
    )
    await service.start()
    log.info(
        "main ready: tz=%s llm_timeout=%ss currency=%s wake every %s min, quiet %s, budget %s",
        s.tz,
        s.llm_timeout,
        s.currency.upper(),
        s.wake_every,
        s.quiet_hours or "never",
        s.wake_budget,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await service.stop()
    await service.drain()
    await bus.close()


if __name__ == "__main__":
    asyncio.run(main())
