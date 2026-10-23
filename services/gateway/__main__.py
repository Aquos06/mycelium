"""Entrypoint: python -m gateway. The environment is read and validated by GatewaySettings (settings.py).

Model keys are the exception: providers.yaml names the env var per provider (`key_env`) and the
gateway reads it when it builds that provider. This is the only place a model key lives.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from mycelium_sdk import NatsBus, NatsKV

from .schemas import GatewayConfig
from .service import GatewayService
from .settings import GatewaySettings

log = logging.getLogger("mycelium.gateway")


async def main() -> None:
    s = GatewaySettings()
    logging.basicConfig(level=s.log_level)
    config = GatewayConfig.from_yaml(s.config)
    bus = NatsBus(s.nats_url, name="gateway")
    await bus.connect()
    kv = await NatsKV(bus.nc, "gateway").open()
    service = GatewayService(bus, config, kv)
    await service.start()
    for slot_name, slot in config.slots.items():
        providers = {n: f"{p.kind}/{p.model} key={p.key_state(os.environ)}" for n, p in slot.providers.items()}
        log.info("slot %s: active=%s shadow=%s providers=%s", slot_name, slot.active, slot.shadow, providers)
        if slot.providers[slot.active].key_state(os.environ) == "missing":
            log.warning(
                "slot %s: active provider %r has no key; calls will fail until it is set", slot_name, slot.active
            )
    log.info("gateway ready: budget=%s USD/month", config.budget_usd_month)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await service.drain()
    await bus.close()


if __name__ == "__main__":
    asyncio.run(main())
