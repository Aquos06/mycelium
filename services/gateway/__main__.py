"""Entrypoint: python -m gateway

Env:
    NATS_URL            nats://nats:4222
    GATEWAY_CONFIG      /srv/gateway/providers.yaml
    <KEY ENV VARS>      ANTHROPIC_API_KEY, OPENAI_API_KEY, ... whatever the configured kinds need
                        (schemas/kinds.py) — the only place a model key lives
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from mycelium_sdk import NatsBus, NatsKV

from .schemas import GatewayConfig
from .service import GatewayService

log = logging.getLogger("mycelium.gateway")


async def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = GatewayConfig.from_yaml(os.environ.get("GATEWAY_CONFIG", "/srv/gateway/providers.yaml"))
    bus = NatsBus(os.environ.get("NATS_URL", "nats://nats:4222"), name="gateway")
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
