"""Entrypoint: python -m memory. The environment is read and validated by MemorySettings (settings.py)."""

from __future__ import annotations

import asyncio
import logging
import signal

from mycelium_sdk import NatsBus
from mycelium_sdk.db import make_engine

from .consolidate import Consolidator
from .events import PostgresEvents
from .index import PostgresIndex
from .schedule import nightly
from .service import MemoryService
from .settings import MemorySettings
from .vault import Vault

log = logging.getLogger("mycelium.memory")


async def main() -> None:
    s = MemorySettings()
    logging.basicConfig(level=s.log_level)
    engine = make_engine(s.database_url)
    index = PostgresIndex(engine, schema=s.schema_name)
    await index.ensure_schema()  # memory's Alembic tree, into its schema
    s.vault_dir.mkdir(parents=True, exist_ok=True)

    bus = NatsBus(s.nats_url, name="memory")
    vault = Vault(s.vault_dir)
    consolidator = Consolidator(bus, vault, index, PostgresEvents(engine), tz=s.tz)
    service = MemoryService(bus, vault, index, consolidator=consolidator)
    await service.start()

    stop = asyncio.Event()
    schedule = (
        asyncio.create_task(nightly(consolidator.run, s.consolidate_at, s.tz, stop)) if s.consolidate_at else None
    )
    log.info(
        "memory ready: vault=%s schema=%s tz=%s consolidate_at=%s",
        s.vault_dir,
        s.schema_name,
        s.tz,
        s.consolidate_at or "off",
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    if schedule:
        await schedule
    await bus.close()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
