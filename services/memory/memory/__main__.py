"""Entrypoint: python -m memory

Env:
    NATS_URL              nats://nats:4222
    MEMORY_DATABASE_URL   falls back to DATABASE_URL until memory gets its own database (ARCHITECTURE §12)
    MEMORY_SCHEMA         memory
    MEMORY_VAULT_DIR      /vault
    MEMORY_TZ             Asia/Taipei   (local day boundaries for consolidation)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from mycelium_sdk import NatsBus

from .events import PostgresEvents
from .index import PostgresIndex
from .service import MemoryService
from .vault import Vault

log = logging.getLogger("mycelium.memory")


async def main() -> None:
    import asyncpg

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    dsn = os.environ.get("MEMORY_DATABASE_URL") or os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    index = PostgresIndex(pool, schema=os.environ.get("MEMORY_SCHEMA", "memory"))
    await index.ensure_schema()

    vault_dir = Path(os.environ.get("MEMORY_VAULT_DIR", "/vault"))
    vault_dir.mkdir(parents=True, exist_ok=True)

    bus = NatsBus(os.environ.get("NATS_URL", "nats://nats:4222"), name="memory")
    service = MemoryService(bus, Vault(vault_dir), index, events=PostgresEvents(pool))
    await service.start()
    log.info("memory ready: vault=%s schema=%s", vault_dir, index.s)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await bus.close()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
