"""Supervisor: owns Docker. Everyone else asks it over the bus.

RPC subjects:
    rpc.sys.deploy  {"name": "hello"}         validate manifest, build, run
    rpc.sys.stop    {"name": "hello"}
    rpc.sys.logs    {"name": "hello", "tail": 100}
    rpc.sys.list    {}
    rpc.sys.health  {}                         pings every running module
Events emitted:
    sys.module.deployed / sys.module.stopped / sys.module.failed
"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

from mycelium_sdk import Bus, ManifestError, Message, NatsBus, load_manifest
from mycelium_sdk.manifest import NAME_RE
from mycelium_sdk.subjects import mod_rpc

from .docker_ops import DockerOps
from .registry import Registry

log = logging.getLogger("mycelium.supervisor")


class Supervisor:
    def __init__(
        self,
        bus: Bus,
        docker: DockerOps,
        registry: Registry,
        modules_dir: Path,
        sdk_dir: Path,
        approved_actuators: set[str] | None = None,
    ) -> None:
        self.bus = bus
        self.docker = docker
        self.registry = registry
        self.modules_dir = modules_dir
        self.sdk_dir = sdk_dir
        self.approved_actuators = approved_actuators or set()
        self._lock = asyncio.Lock()  # one deploy at a time keeps Docker state sane

    async def start(self, build_base: bool = True, reconcile: bool = False) -> None:
        if build_base:
            await asyncio.to_thread(self.docker.ensure_base_image, self.sdk_dir)
        handlers = {
            "deploy": self.deploy,
            "stop": self.stop,
            "logs": self.logs,
            "list": self.list,
            "health": self.health,
        }
        for action, fn in handlers.items():
            await self.bus.subscribe(f"rpc.sys.{action}", self._wrap(fn), queue="supervisor")
        log.info("supervisor ready")
        if reconcile:
            await self.reconcile()

    async def reconcile(self) -> dict[str, str]:
        """Redeploy every module the registry says should be running, from the code on disk now.
        This is how a CD deploy rolls new module code out: new supervisor starts -> reconcile."""
        results: dict[str, str] = {}
        for row in await self.registry.all():
            if row["status"] != "running":
                continue
            name = row["name"]
            try:
                await self.deploy({"name": name})
                results[name] = "redeployed"
            except FileNotFoundError:
                await self.registry.set_status(name, "retired")
                results[name] = "retired (folder gone)"
            except Exception as e:
                results[name] = f"failed: {e}"
                log.exception("reconcile failed for %s", name)
        if results:
            await self.bus.publish("sys.reconciled", {"modules": results})
        return results

    def _wrap(self, fn):
        async def handler(msg: Message) -> None:
            try:
                result = await fn(msg.data)
                payload = {"ok": True, **result}
            except (ManifestError, ValueError, PermissionError, FileNotFoundError) as e:
                payload = {"ok": False, "error": str(e)}
            except Exception as e:  # never let one bad request kill the supervisor
                log.exception("unexpected error")
                payload = {"ok": False, "error": f"internal: {e}"}
            if msg.reply:
                await msg.respond(payload)

        return handler

    def _module_dir(self, name: Any) -> Path:
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ValueError(f"invalid module name: {name!r}")
        d = (self.modules_dir / name).resolve()
        if d.parent != self.modules_dir.resolve():
            raise ValueError("module path escapes modules dir")
        if not d.is_dir():
            raise FileNotFoundError(f"no module folder: {name}")
        return d

    async def deploy(self, data: dict[str, Any]) -> dict[str, Any]:
        name = data.get("name")
        d = self._module_dir(name)
        manifest = load_manifest(d / "manifest.yaml")
        if manifest.name != name:
            raise ManifestError(f"folder '{name}' but manifest.name '{manifest.name}'")
        if manifest.permissions.actuation and name not in self.approved_actuators:
            raise PermissionError(
                f"module '{name}' requests actuation; add it to APPROVED_ACTUATORS after reviewing it"
            )
        async with self._lock:
            await self.registry.upsert(manifest, "building", None)
            try:
                image = await asyncio.to_thread(self.docker.build_module, d, manifest)
                info = await asyncio.to_thread(self.docker.run_module, image, manifest)
            except Exception as e:
                await self.registry.set_status(name, "failed")
                await self.bus.publish("sys.module.failed", {"name": name, "error": str(e)})
                raise
            await self.registry.upsert(manifest, "running", image)
        await self.bus.publish("sys.module.deployed", {"name": name, "version": manifest.version, "image": image})
        return {"name": name, "image": image, "status": info.status}

    async def stop(self, data: dict[str, Any]) -> dict[str, Any]:
        name = data.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ValueError(f"invalid module name: {name!r}")
        stopped = await asyncio.to_thread(self.docker.stop_module, name)
        await self.registry.set_status(name, "stopped")
        if stopped:
            await self.bus.publish("sys.module.stopped", {"name": name})
        return {"name": name, "stopped": stopped}

    async def logs(self, data: dict[str, Any]) -> dict[str, Any]:
        name = data.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ValueError(f"invalid module name: {name!r}")
        tail = max(1, min(int(data.get("tail", 100)), 2000))
        return {"name": name, "logs": await asyncio.to_thread(self.docker.logs, name, tail)}

    async def list(self, _data: dict[str, Any]) -> dict[str, Any]:
        containers = {c.name: c for c in await asyncio.to_thread(self.docker.list_modules)}
        rows = await self.registry.all()
        out = []
        for r in rows:
            c = containers.get(r["name"])
            out.append({**r, "container": c.status if c else None})
        return {"modules": out}

    async def health(self, _data: dict[str, Any]) -> dict[str, Any]:
        results = {}
        for c in await asyncio.to_thread(self.docker.list_modules):
            if c.status != "running":
                results[c.name] = {"ok": False, "status": c.status}
                continue
            try:
                results[c.name] = await self.bus.request(mod_rpc(c.name, "health"), {}, timeout=2)
            except Exception as e:
                results[c.name] = {"ok": False, "error": type(e).__name__}
        return {"modules": results}


async def main() -> None:
    from .docker_ops import RealDockerOps
    from .registry import PostgresRegistry
    from .settings import SupervisorSettings

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
