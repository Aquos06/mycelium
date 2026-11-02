"""Entrypoint: python -m builder. The environment is read and validated by BuilderSettings (settings.py)."""

from __future__ import annotations

import asyncio
import logging
import signal

from mycelium_sdk import NatsBus, NatsKV

from .coders import AgentCoder, AgentRoster, MyceliumCoder
from .pipeline import Pipeline
from .prompts import Brief
from .repo import GrownRepo
from .service import BuilderService
from .settings import BuilderSettings
from .workspace import Workspace

log = logging.getLogger("mycelium.builder")


async def main() -> None:
    s = BuilderSettings()
    logging.basicConfig(level=s.log_level)
    bus = NatsBus(s.nats_url, name="builder")
    await bus.connect()
    kv = await NatsKV(bus.nc, "builder").open()
    repo = GrownRepo(s.grown_dir)
    try:
        await repo.ensure()  # the supervisor counts GROWN_DIR as there only once it is a repo
    except (OSError, RuntimeError) as e:  # keep running: every build is refused with the reason until it is fixed
        log.error("GROWN_DIR %s is not writable by the builder: %s (create it as you: mkdir -p grown)", s.grown_dir, e)
    workspace = Workspace(s.grown_dir, s.template_dir)
    pipeline = Pipeline(
        bus,
        workspace,
        repo,
        Brief.load(s.template_dir, s.example_dir),
        max_rounds=s.max_rounds,
        verify_timeout=s.verify_timeout,
        deploy_timeout=s.deploy_timeout,
    )
    roster = AgentRoster(bus)  # one rpc.sys.agents for all the agents
    coders = {
        "mycelium": MyceliumCoder(
            bus,
            slot=s.coder_slot,
            timeout=s.coder_llm_timeout,
            max_calls=s.coder_max_calls,
            max_usd=s.coder_max_usd,
        ),
        **{name: AgentCoder(bus, name, timeout=s.agent_timeout, roster=roster) for name in s.agent_names},
    }
    service = BuilderService(
        bus, kv, pipeline, workspace, coders, s.coder, max_queue=s.max_queue, build_timeout=s.build_timeout
    )
    await service.start()
    log.info("builder ready: coder=%s grown=%s", s.coder, s.grown_dir)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await service.stop()
    await bus.close()


if __name__ == "__main__":
    asyncio.run(main())
