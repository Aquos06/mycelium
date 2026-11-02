"""Thin wrapper around the Docker SDK. The only code in the system that touches Docker.

Kept behind a small interface so the supervisor's logic can be unit-tested with a fake.
Everything is namespaced by STACK so dev / staging / production can share one Docker host.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from mycelium_sdk import Manifest

log = logging.getLogger("mycelium.supervisor.docker")

LABEL = "mycelium.module"
STACK_LABEL = "mycelium.stack"
# a verify run and a coding agent are not modules: their images and containers never carry LABEL or STACK_LABEL
# (a container inherits its image's labels), so list_modules and health never see them. Their containers carry
# the stack as the label's value: dev, staging and production share one Docker host, and each sweeps its own.
VERIFY_LABEL = "mycelium.verify"
AGENT_LABEL = "mycelium.agent"
VERIFY_COMMAND = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
OUTPUT_TAIL = 4000


class ContainerInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    status: str
    image: str


class TestRun(BaseModel):
    """A module's tests, run once in a throwaway container (DockerOps.run_tests)."""

    __test__ = False  # not a pytest class, whatever its name

    exit_code: int
    output: str  # the tail of what pytest printed
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class AgentResult(BaseModel):
    """One coding agent run (DockerOps.run_agent): how it ended, what it printed, the folder it left (a tar)."""

    exit_code: int
    output: str
    timed_out: bool = False
    archive: bytes = b""


class DockerOps(Protocol):
    def ensure_base_image(self, sdk_dir: Path) -> None: ...
    def build_module(self, module_dir: Path, manifest: Manifest, verify: bool = False) -> str: ...
    def run_tests(self, image: str, timeout: float) -> TestRun: ...
    def remove_image(self, image: str) -> None: ...
    def build_agent_image(self, name: str, context: Path) -> str: ...
    def sweep(self) -> int: ...
    def run_agent(
        self, image: str, work: bytes, env: dict[str, str], timeout: float, memory_mb: int, cpus: float
    ) -> AgentResult: ...
    def run_module(self, image: str, manifest: Manifest) -> ContainerInfo: ...
    def stop_module(self, name: str) -> bool: ...
    def logs(self, name: str, tail: int = 100) -> str: ...
    def list_modules(self) -> list[ContainerInfo]: ...


class RealDockerOps:
    def __init__(
        self, nats_url: str, bus_network: str, internet_network: str, stack: str = "mycelium", tz: str = "UTC"
    ) -> None:
        import docker  # lazy: unit tests use a fake

        self.client = docker.from_env()
        self.nats_url = nats_url
        self.bus_network = bus_network  # internal network: bus only, no internet
        self.internet_network = internet_network  # attached only when permissions.network
        self.stack = stack
        self.tz = tz  # every module's TZ: mod.today() is the user's day
        self.base_image = f"{stack}/module-base:latest"

    def ensure_base_image(self, sdk_dir: Path) -> None:
        log.info("building %s from %s", self.base_image, sdk_dir)
        self.client.images.build(path=str(sdk_dir), tag=self.base_image, rm=True)

    def build_module(self, module_dir: Path, manifest: Manifest, verify: bool = False) -> str:
        """The module's image. `verify` tags it apart (`:verify`), so testing never replaces a running version."""
        tag = f"{self.stack}/mod-{manifest.name}:{'verify' if verify else manifest.version}"
        labels = {VERIFY_LABEL: manifest.name} if verify else {LABEL: manifest.name, STACK_LABEL: self.stack}
        self._build(module_dir, tag, labels)
        return tag

    def _build(self, context: Path, tag: str, labels: dict[str, str]) -> None:
        import docker

        try:
            self.client.images.build(
                path=str(context), tag=tag, rm=True, buildargs={"BASE_IMAGE": self.base_image}, labels=labels
            )
        except docker.errors.BuildError as e:  # the log says why (a requirement that does not install)
            lines = "".join(str(c.get("stream") or c.get("error") or "") for c in e.build_log or [])
            raise RuntimeError(f"{e.msg}\n{lines[-OUTPUT_TAIL:]}") from e

    def run_tests(self, image: str, timeout: float) -> TestRun:
        """The module's own tests in the image that would ship, with nothing to reach and nothing to read: no
        network, no environment beyond TZ (no NATS_URL, no keys), a read-only filesystem with a small /tmp,
        no capabilities, bounded memory and processes. Generated code runs nowhere else before deploy."""
        c = self.client.containers.run(
            image,
            command=VERIFY_COMMAND,
            detach=True,
            network_mode="none",
            environment={"TZ": self.tz, "PYTHONDONTWRITEBYTECODE": "1"},
            mem_limit="512m",
            nano_cpus=int(1e9),
            pids_limit=256,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            read_only=True,
            tmpfs={"/tmp": "rw,size=64m"},
            labels={VERIFY_LABEL: self.stack},
        )
        code, timed_out = self._wait(c, timeout)
        try:
            output = c.logs().decode(errors="replace")
        finally:
            c.remove(force=True)
        return TestRun(exit_code=code, output=output[-OUTPUT_TAIL:], timed_out=timed_out)

    def remove_image(self, image: str) -> None:
        import docker

        try:
            self.client.images.remove(image, force=True)
        except docker.errors.ImageNotFound:
            pass

    def build_agent_image(self, name: str, context: Path) -> str:
        """A coding agent's image, FROM module-base: Python, the SDK and pytest, so it can run the tests itself."""
        tag = f"{self.stack}/coder-{name.replace('_', '-')}:latest"
        self._build(context, tag, {AGENT_LABEL: name})
        return tag

    def sweep(self) -> int:
        """This stack's verify and agent containers a restart left behind (an agent's holds its key), removed on
        start. Never another stack's: theirs may be running now. Best effort: a container Docker cannot remove
        (dead, already going) is logged and left, so the supervisor still starts."""
        gone = 0
        for label in (VERIFY_LABEL, AGENT_LABEL):
            for c in self.client.containers.list(all=True, filters={"label": label}):
                if not self._ours(c.labels.get(label, "")):
                    continue
                try:
                    c.remove(force=True)
                    gone += 1
                except Exception as e:
                    log.warning("could not remove leftover container %s: %s", c.name, e)
        return gone

    def _ours(self, value: str) -> bool:
        """The label's value is the stack; before it was, it was the image tag, which starts with the stack."""
        return value == self.stack or value.startswith(f"{self.stack}/")

    def run_agent(
        self, image: str, work: bytes, env: dict[str, str], timeout: float, memory_mb: int, cpus: float
    ) -> AgentResult:
        """A coding agent on a copy of the staged module: `work` (a tar) goes in at /work, the folder comes back
        out as a tar. The default bridge network reaches its model and the internet, never the mesh: no NATS,
        no Postgres. Not root, no capabilities, bounded memory, CPU and processes; removed afterwards."""
        c = self.client.containers.create(
            image,
            detach=True,
            environment=env,
            working_dir="/work/module",
            network_mode="bridge",
            mem_limit=f"{memory_mb}m",
            nano_cpus=int(cpus * 1e9),
            pids_limit=512,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            labels={AGENT_LABEL: self.stack},
        )
        try:
            c.put_archive("/work", work)
            c.start()
            code, timed_out = self._wait(c, timeout)
            output = c.logs().decode(errors="replace")
            chunks, _ = c.get_archive("/work/module")
            archive = b"".join(chunks)
        finally:
            c.remove(force=True)
        return AgentResult(exit_code=code, output=output[-OUTPUT_TAIL:], timed_out=timed_out, archive=archive)

    @staticmethod
    def _wait(c, timeout: float) -> tuple[int, bool]:
        try:
            return int(c.wait(timeout=timeout).get("StatusCode", 1)), False
        except Exception:  # the client's read timeout: it ran too long
            try:
                c.kill()
            except Exception:  # it ended just now; remove() still cleans up
                pass
            return -1, True

    def _container_name(self, name: str) -> str:
        return f"{self.stack}-mod-{name}"

    def stop_module(self, name: str) -> bool:
        import docker

        try:
            c = self.client.containers.get(self._container_name(name))
        except docker.errors.NotFound:
            return False
        c.stop(timeout=10)
        c.remove()
        return True

    def run_module(self, image: str, manifest: Manifest) -> ContainerInfo:
        self.stop_module(manifest.name)
        c = self.client.containers.run(
            image,
            name=self._container_name(manifest.name),
            detach=True,
            network=self.bus_network,
            environment={"NATS_URL": self.nats_url, "MODULE": manifest.name, "TZ": self.tz},
            volumes={f"{self.stack}-data-{manifest.name}": {"bind": "/data", "mode": "rw"}},
            mem_limit=f"{manifest.resources.memory_mb}m",
            nano_cpus=int(manifest.resources.cpus * 1e9),
            labels={LABEL: manifest.name, STACK_LABEL: self.stack, "mycelium.version": manifest.version},
            restart_policy={"Name": "unless-stopped"},
        )
        if manifest.permissions.network:
            self.client.networks.get(self.internet_network).connect(c)
        c.reload()
        return ContainerInfo(name=manifest.name, status=c.status, image=image)

    def logs(self, name: str, tail: int = 100) -> str:
        c = self.client.containers.get(self._container_name(name))
        return c.logs(tail=tail).decode(errors="replace")

    def list_modules(self) -> list[ContainerInfo]:
        out = []
        for c in self.client.containers.list(all=True, filters={"label": f"{STACK_LABEL}={self.stack}"}):
            out.append(
                ContainerInfo(
                    name=c.labels.get(LABEL, c.name),
                    status=c.status,
                    image=(c.image.tags or ["?"])[0],
                )
            )
        return out
