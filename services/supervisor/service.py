"""Supervisor: owns Docker. Everyone else asks it over the bus.

RPC subjects (the requests and replies are in schemas.py):
    rpc.sys.deploy  ModuleRef        validate manifest, build, run
    rpc.sys.verify  VerifyRequest    run its tests in a locked-down throwaway container
    rpc.sys.agent   AgentRequest     a coding agent on a copy of a staged build; the folder comes back
    rpc.sys.agents  {}               the coding agents and whether each can run now
    rpc.sys.stop    ModuleRef
    rpc.sys.logs    LogsRequest
    rpc.sys.list    {}               the registry's modules, and every module folder on disk
    rpc.sys.health  {}               pings every running module
Events emitted:
    sys.module.deployed / sys.module.stopped / sys.module.failed

Modules live in two roots: MODULES_DIR holds the hand-written ones (hello), GROWN_DIR the grown ones, a git
repo of their own that the builder writes. A build is staged in GROWN_DIR/.staging/<name> until verify passes;
`.staging` can never be a module name, so nothing half-written is ever deployed.

Coding agents (agents.py) run here too, because only the supervisor holds Docker: each in its own container,
on a copy of the staged folder, with only the variables its recipe names (its model's address, its key).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from mycelium_sdk import Bus, ManifestError, Message, load_manifest, validation_message
from mycelium_sdk.manifest import NAME_RE
from mycelium_sdk.subjects import mod_rpc

from . import agents as agent_files
from .docker_ops import DockerOps
from .registry import Registry
from .schemas import (
    AgentList,
    AgentRecipe,
    AgentRequest,
    AgentRun,
    Deployed,
    HealthReport,
    Logs,
    LogsRequest,
    ModuleHealth,
    ModuleList,
    ModuleRef,
    ModuleRow,
    ModuleStatus,
    Stopped,
    VerifyRequest,
    VerifyResult,
    VerifyStage,
)

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
        agents: dict[str, AgentRecipe] | None = None,
        agents_dir: Path | None = None,
        agent_timeout: float = 3600.0,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.bus = bus
        self.docker = docker
        self.registry = registry
        self.modules_dir = modules_dir
        self.grown_dir = grown_dir
        self.sdk_dir = sdk_dir
        self.approved_actuators = approved_actuators or set()
        self.verify_timeout = verify_timeout
        self.agents = agents or {}
        self.agents_dir = agents_dir
        self.agent_timeout = agent_timeout
        self.env = os.environ if env is None else env  # where an agent's address and key come from
        self._lock = asyncio.Lock()  # one deploy at a time keeps Docker state sane
        self._verify_lock = asyncio.Lock()  # and one test run: each one builds an image
        self._agent_lock = asyncio.Lock()  # and one agent: the builder runs one build at a time anyway
        self._agent_images: dict[str, str] = {}  # built once per start: a round never waits for a rebuild

    async def start(self, build_base: bool = True, reconcile: bool = False) -> None:
        if build_base:
            await asyncio.to_thread(self.docker.ensure_base_image, self.sdk_dir)
            swept = await asyncio.to_thread(self.docker.sweep)
            if swept:
                log.info("removed %d verify or agent containers a restart left behind", swept)
        handlers = {
            "deploy": self.deploy,
            "verify": self.verify,
            "agent": self.agent,
            "agents": self.list_agents,
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
            if row.status != ModuleStatus.RUNNING:
                continue
            name = row.name
            try:
                await self.deploy({"name": name})
                results[name] = "redeployed"
            except FileNotFoundError:
                if mounted:
                    await self.registry.set_status(name, ModuleStatus.RETIRED)
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
                result: BaseModel = await fn(msg.data)
                payload = {"ok": True, **result.model_dump(mode="json")}
            except ValidationError as e:
                payload = {"ok": False, "error": validation_message(e)}
            except (ManifestError, ValueError, PermissionError, FileNotFoundError) as e:
                payload = {"ok": False, "error": str(e)}
            except Exception as e:  # never let one bad request kill the supervisor
                log.exception("unexpected error")
                payload = {"ok": False, "error": f"internal: {e}"}
            if msg.reply:
                try:
                    await msg.respond(payload)
                except Exception as e:  # too big for one NATS message, most likely: answer anyway, never leave a wait
                    log.exception("could not send the reply")
                    await msg.respond({"ok": False, "error": f"the reply could not be sent: {type(e).__name__}: {e}"})

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

    def _module_dir(self, name: str, staging: bool = False) -> Path:
        """A deployable module's folder, in exactly one root; or, with `staging`, a build waiting for verify.
        `name` is a ModuleName: the request models have checked it."""
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

    async def deploy(self, data: dict[str, Any]) -> Deployed:
        name = ModuleRef.model_validate(data).name
        d = self._module_dir(name)
        manifest = load_manifest(d / "manifest.yaml")
        if manifest.name != name:
            raise ManifestError(f"folder '{name}' but manifest.name '{manifest.name}'")
        if manifest.permissions.actuation and name not in self.approved_actuators:
            raise PermissionError(
                f"module '{name}' requests actuation; add it to APPROVED_ACTUATORS after reviewing it"
            )
        async with self._lock:
            await self.registry.upsert(manifest, ModuleStatus.BUILDING, None)
            try:
                image = await asyncio.to_thread(self.docker.build_module, d, manifest)
                info = await asyncio.to_thread(self.docker.run_module, image, manifest)
            except Exception as e:
                await self.registry.set_status(name, ModuleStatus.FAILED)
                await self.bus.publish("sys.module.failed", {"name": name, "error": str(e)})
                raise
            await self.registry.upsert(manifest, ModuleStatus.RUNNING, image)
        await self.bus.publish("sys.module.deployed", {"name": name, "version": manifest.version, "image": image})
        return Deployed(name=name, image=image, status=info.status)

    async def verify(self, data: dict[str, Any]) -> VerifyResult:
        """A module's tests in a throwaway container of the image that would ship (DockerOps.run_tests): the
        builder's independent check, and the only place generated code runs before it is deployed."""
        req = VerifyRequest.model_validate(data)
        name = req.name
        d = self._module_dir(name, staging=req.staging)
        manifest = load_manifest(d / "manifest.yaml")
        if manifest.name != name:
            raise ManifestError(f"folder '{name}' but manifest.name '{manifest.name}'")
        t0 = time.monotonic()
        async with self._verify_lock:
            try:
                image = await asyncio.to_thread(self.docker.build_module, d, manifest, True)
            except Exception as e:  # a requirement that does not install, a Dockerfile that does not build
                return VerifyResult(
                    name=name, passed=False, stage=VerifyStage.BUILD, output=str(e)[-4000:], seconds=_since(t0)
                )
            try:
                run = await asyncio.to_thread(self.docker.run_tests, image, self.verify_timeout)
            finally:
                await asyncio.to_thread(self.docker.remove_image, image)
        return VerifyResult(
            name=name,
            passed=run.passed,
            stage=VerifyStage.TESTS,
            exit_code=run.exit_code,
            timed_out=run.timed_out,
            output=run.output,
            seconds=_since(t0),
        )

    async def agent(self, data: dict[str, Any]) -> AgentRun:
        """A coding agent on a copy of a staged build (agents.py): the folder as it left it comes back, keys out."""
        req = AgentRequest.model_validate(data)
        name, agent = req.name, req.agent
        recipe = self.agents.get(agent)
        if recipe is None or self.agents_dir is None:
            raise ValueError(f"no agent {agent!r}; one of {', '.join(self.agents) or 'none'}")
        reason = agent_files.not_ready(recipe, self.env)
        if reason:
            raise ValueError(f"{agent} cannot run: {reason}")
        d = self._module_dir(name, staging=True)
        timeout = min(max(req.timeout or self.agent_timeout, 10.0), self.agent_timeout)
        env = {
            **agent_files.agent_env(recipe, self.env),
            "MODULE_NAME": name.replace("-", "_"),
            "TZ": self.env.get("MODULE_TZ") or "UTC",
            "HOME": "/home/module",
        }
        hidden = agent_files.secrets(env)
        t0 = time.monotonic()
        async with self._agent_lock:
            if agent not in self._agent_images:
                self._agent_images[agent] = await asyncio.to_thread(
                    self.docker.build_agent_image, agent, self.agents_dir / agent
                )
            work = await asyncio.to_thread(agent_files.pack, d, req.prompt)
            run = await asyncio.to_thread(
                self.docker.run_agent, self._agent_images[agent], work, env, timeout, recipe.memory_mb, recipe.cpus
            )
        left = await asyncio.to_thread(agent_files.unpack, run.archive)
        files = {rel: agent_files.redact(text, hidden) for rel, text in left.files.items()}
        return AgentRun(
            agent=agent,
            name=name,
            exit_code=run.exit_code,
            timed_out=run.timed_out,
            output=agent_files.redact(run.output, hidden),
            files=files,
            skipped=left.skipped,
            skipped_more=left.skipped_more,
            seconds=_since(t0),
        )

    async def list_agents(self, _data: dict[str, Any]) -> AgentList:
        return AgentList(agents=agent_files.describe(self.agents, self.env))

    async def stop(self, data: dict[str, Any]) -> Stopped:
        name = ModuleRef.model_validate(data).name
        stopped = await asyncio.to_thread(self.docker.stop_module, name)
        await self.registry.set_status(name, ModuleStatus.STOPPED)
        if stopped:
            await self.bus.publish("sys.module.stopped", {"name": name})
        return Stopped(name=name, stopped=stopped)

    async def logs(self, data: dict[str, Any]) -> Logs:
        req = LogsRequest.model_validate(data)
        tail = max(1, min(req.tail, 2000))
        return Logs(name=req.name, logs=await asyncio.to_thread(self.docker.logs, req.name, tail))

    async def list(self, _data: dict[str, Any]) -> ModuleList:
        containers = {c.name: c for c in await asyncio.to_thread(self.docker.list_modules)}
        rows = [
            ModuleRow(**r.model_dump(), container=c.status if (c := containers.get(r.name)) else None)
            for r in await self.registry.all()
        ]
        return ModuleList(modules=rows, folders=self._folders())

    def _folders(self) -> list[str]:
        """Every module folder on disk in either root, deployed or not: names a build may not take."""
        names = set()
        for root in self.roots:
            if root.is_dir():
                names |= {d.name for d in root.iterdir() if d.is_dir() and NAME_RE.fullmatch(d.name)}
        return sorted(names)

    async def health(self, _data: dict[str, Any]) -> HealthReport:
        results: dict[str, ModuleHealth] = {}
        for c in await asyncio.to_thread(self.docker.list_modules):
            if c.status != "running":
                results[c.name] = ModuleHealth(ok=False, status=c.status)
                continue
            try:
                reply = await self.bus.request(mod_rpc(c.name, "health"), {}, timeout=2)
                results[c.name] = ModuleHealth.model_validate({"ok": False, **reply})  # no `ok`: not healthy
            except Exception as e:
                results[c.name] = ModuleHealth(ok=False, error=type(e).__name__)
        return HealthReport(modules=results)


def _since(t0: float) -> float:
    return round(time.monotonic() - t0, 1)
