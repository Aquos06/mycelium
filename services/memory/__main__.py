"""Entrypoint: python -m memory. The environment is read and validated by MemorySettings (settings.py)."""

from __future__ import annotations

import asyncio
import logging
import signal

from mycelium_sdk import NatsBus
from mycelium_sdk.db import make_engine

from .consolidate import ConsolidationError, Consolidator
from .embedder import Embedder
from .events import PostgresEvents
from .index import PostgresIndex
from .schedule import catch_up, every, nightly
from .service import MemoryService
from .settings import MemorySettings
from .vault import Vault

log = logging.getLogger("mycelium.memory")

CATCH_UP_DAYS = 7  # at start, consolidate recent days a restart or outage skipped


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
    embedder = (
        Embedder(bus, index, batch=s.embed_batch, timeout=s.embed_timeout, min_score=s.embed_min_score)
        if s.embed
        else None
    )
    service = MemoryService(bus, vault, index, consolidator=consolidator, embedder=embedder, today=s.today)
    await service.start()

    stop = asyncio.Event()

    async def has_summary(day) -> bool:
        return await index.summary("day", day.isoformat()) is not None

    async def consolidate(day) -> None:
        await consolidator.run(day)
        if embedder:
            await embedder.sweep()  # the new summary and the notes it touched get their vectors right away

    async def scheduled() -> None:
        await catch_up(consolidate, has_summary, s.today(), CATCH_UP_DAYS)
        for period, key in await consolidator.rollups.missing(s.today(), CATCH_UP_DAYS):
            try:
                await consolidator.rollup(period, key)
            except ConsolidationError as e:  # traced already; the next start tries again
                log.warning("catch-up %s rollup %s failed: %s", period, key, e)
        await nightly(consolidate, s.consolidate_at, s.tz, stop)

    schedule = asyncio.create_task(scheduled()) if s.consolidate_at else None
    sweeps = asyncio.create_task(every(embedder.sweep, s.embed_every, stop)) if embedder else None
    log.info(
        "memory ready: vault=%s schema=%s tz=%s consolidate_at=%s embed=%s",
        s.vault_dir,
        s.schema_name,
        s.tz,
        s.consolidate_at or "off",
        f"every {s.embed_every} min" if embedder and s.embed_every else ("on" if embedder else "off"),
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    if schedule:
        await schedule
    if sweeps:
        await sweeps
    await bus.close()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
