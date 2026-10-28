"""Entrypoint: python -m supervisor. The environment is read and validated by SupervisorSettings (settings.py)."""

from __future__ import annotations

import asyncio
import logging
import signal

from mycelium_sdk import NatsBus

from .docker_ops import RealDockerOps
from .registry import PostgresRegistry
from .service import Supervisor
from .settings import SupervisorSettings


async def main() -> None:
    s = SupervisorSettings()
    logging.basicConfig(level=s.log_level)
    bus = NatsBus(s.nats_url, name="supervisor")
    await bus.connect()
    registry = PostgresRegistry(s.database_url)
    await registry.connect()
    docker = RealDockerOps(
        nats_url=s.nats_url,
        bus_network=s.module_network or "",
        internet_network=s.internet_network or "",
        stack=s.stack,
    )
    sup = Supervisor(
        bus=bus,
        docker=docker,
        registry=registry,
        modules_dir=s.modules_dir,
        sdk_dir=s.sdk_dir,
        approved_actuators=s.approved,
    )
    await sup.start(reconcile=s.reconcile_on_start)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await bus.close()


if __name__ == "__main__":
    asyncio.run(main())
