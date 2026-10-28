"""Supervisor: owns Docker. Everyone else asks it over the bus.

RPC subjects:
    rpc.sys.deploy  {"name": "hello"}         validate manifest, build, run
    rpc.sys.verify  {"name": "expenses", "staging": true}
                                               run its tests in a locked-down throwaway container
    rpc.sys.stop    {"name": "hello"}
    rpc.sys.logs    {"name": "hello", "tail": 100}
    rpc.sys.list    {}
    rpc.sys.health  {}                         pings every running module
Events emitted:
    sys.module.deployed / sys.module.stopped / sys.module.failed

Modules live in two roots: MODULES_DIR holds the hand-written ones (hello), GROWN_DIR the grown ones, a git
repo of their own that the builder writes. A build is staged in GROWN_DIR/.staging/<name> until verify passes;
`.staging` can never be a module name, so nothing half-written is ever deployed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from mycelium_sdk import Bus, ManifestError, Message, load_manifest
from mycelium_sdk.manifest import NAME_RE
from mycelium_sdk.subjects import mod_rpc

from .docker_ops import DockerOps
from .registry import Registry
from .schemas import VerifyResult

log = logging.getLogger("mycelium.supervisor")

STAGING = ".staging"  # GROWN_DIR/.staging/<name>: a build before it passes verify


class Supervisor:
    def __init__(
        self,
        bus: Bus,
        docker: DockerOps,
        registry: Registry,
        modules_dir: Path,
        sdk_dir: Path,
        approved_actuators: set[str] | None = None,
        grown_dir: Path | None = None,
        verify_timeout: float = 300.0,
    ) -> None:
        self.bus = bus
        self.docker = docker
        self.registry = registry
        self.modules_dir = modules_dir
        self.grown_dir = grown_dir
        self.sdk_dir = sdk_dir
        self.approved_actuators = approved_actuators or set()
        self.verify_timeout = verify_timeout
        self._lock = asyncio.Lock()  # one deploy at a time keeps Docker state sane
        self._verify_lock = asyncio.Lock()  # and one test run: each one builds an image

    async def start(self, build_base: bool = True, reconcile: bool = False) -> None:
        if build_base:
            await asyncio.to_thread(self.docker.ensure_base_image, self.sdk_dir)
        handlers = {
            "deploy": self.deploy,
            "verify": self.verify,
            "stop": self.stop,
            "logs": self.logs,
            "list": self.list,
            "health": self.health,
        }
        for action, fn in handlers.items():
            await self.bus.subscribe(f"rpc.sys.{action}", self._wrap(fn), queue="supervisor")
        if self.grown_dir is not None and not self._grown_is_repo():
            log.warning("GROWN_DIR %s is not a git repo yet: no grown module can be found there", self.grown_dir)
        log.info("supervisor ready")
        if reconcile:
            await self.reconcile()

    async def reconcile(self) -> dict[str, str]:
        """Redeploy every module the registry says should be running, from the code on disk now.
        This is how a CD deploy rolls new module code out: new supervisor starts -> reconcile."""
        results: dict[str, str] = {}
        mounted = self._roots_mounted()
        for row in await self.registry.all():
            if row["status"] != "running":
                continue
            name = row["name"]
            try:
                await self.deploy({"name": name})
                results[name] = "redeployed"
            except FileNotFoundError:
                if mounted:
                    await self.registry.set_status(name, "retired")
                    results[name] = "retired (folder gone)"
                else:  # retiring now would retire every module of the missing root, for good
                    results[name] = "kept (a modules root is not mounted)"
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

    @property
    def roots(self) -> list[Path]:
        return [self.modules_dir] if self.grown_dir is None else [self.modules_dir, self.grown_dir]

    def _grown_is_repo(self) -> bool:
        """The builder makes GROWN_DIR a git repo on its first build. Without .git it is not there, or it is
        the empty folder Docker creates for a bind mount whose source is missing."""
        return self.grown_dir is not None and (self.grown_dir / ".git").exists()

    def _roots_mounted(self) -> bool:
        return self.modules_dir.is_dir() and (self.grown_dir is None or self._grown_is_repo())

    @staticmethod
    def _inside(root: Path, name: str) -> Path:
        d = (root / name).resolve()
        if d.parent != root.resolve():
            raise ValueError("module path escapes modules dir")
        return d

    def _module_dir(self, name: Any, staging: bool = False) -> Path:
        """A deployable module's folder, in exactly one root; or, with `staging`, a build waiting for verify."""
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ValueError(f"invalid module name: {name!r}")
        if staging:
            if self.grown_dir is None:
                raise FileNotFoundError("no GROWN_DIR, so nothing is ever staged")
            d = self._inside(self.grown_dir / STAGING, name)
            if not d.is_dir():
                raise FileNotFoundError(f"nothing staged for {name}")
            return d
        found = [d for root in self.roots if (d := self._inside(root, name)).is_dir()]
        if len(found) > 1:
            raise ValueError(f"module {name!r} is in more than one place: {', '.join(map(str, found))}")
        if not found:
            raise FileNotFoundError(f"no module folder: {name}")
        return found[0]

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

    async def verify(self, data: dict[str, Any]) -> dict[str, Any]:
        """A module's tests in a throwaway container of the image that would ship (DockerOps.run_tests): the
        builder's independent check, and the only place generated code runs before it is deployed."""
        name = data.get("name")
        d = self._module_dir(name, staging=bool(data.get("staging", False)))
        manifest = load_manifest(d / "manifest.yaml")
        if manifest.name != name:
            raise ManifestError(f"folder '{name}' but manifest.name '{manifest.name}'")
        t0 = time.monotonic()
        async with self._verify_lock:
            try:
                image = await asyncio.to_thread(self.docker.build_module, d, manifest, True)
            except Exception as e:  # a requirement that does not install, a Dockerfile that does not build
                result = VerifyResult(name=name, passed=False, stage="build", output=str(e)[-4000:], seconds=_since(t0))
                return result.model_dump()
            try:
                run = await asyncio.to_thread(self.docker.run_tests, image, self.verify_timeout)
            finally:
                await asyncio.to_thread(self.docker.remove_image, image)
        result = VerifyResult(
            name=name,
            passed=run.passed,
            stage="tests",
            exit_code=run.exit_code,
            timed_out=run.timed_out,
            output=run.output,
            seconds=_since(t0),
        )
        return result.model_dump()

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


def _since(t0: float) -> float:
    return round(time.monotonic() - t0, 1)
