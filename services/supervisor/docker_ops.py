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
VERIFY_LABEL = "mycelium.verify"  # never STACK_LABEL: a verify run is not a module and stays out of list_modules
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


class DockerOps(Protocol):
    def ensure_base_image(self, sdk_dir: Path) -> None: ...
    def build_module(self, module_dir: Path, manifest: Manifest, verify: bool = False) -> str: ...
    def run_tests(self, image: str, timeout: float) -> TestRun: ...
    def remove_image(self, image: str) -> None: ...
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
        import docker

        tag = f"{self.stack}/mod-{manifest.name}:{'verify' if verify else manifest.version}"
        try:
            self.client.images.build(
                path=str(module_dir),
                tag=tag,
                rm=True,
                buildargs={"BASE_IMAGE": self.base_image},
                labels={LABEL: manifest.name, STACK_LABEL: self.stack},
            )
        except docker.errors.BuildError as e:  # the log says why (a requirement that does not install)
            lines = "".join(str(c.get("stream") or c.get("error") or "") for c in e.build_log or [])
            raise RuntimeError(f"{e.msg}\n{lines[-OUTPUT_TAIL:]}") from e
        return tag

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
            labels={VERIFY_LABEL: image},
        )
        timed_out = False
        try:
            code = int(c.wait(timeout=timeout).get("StatusCode", 1))
        except Exception:  # the client's read timeout: the tests ran too long
            timed_out, code = True, -1
            try:
                c.kill()
            except Exception:  # it ended just now; remove() below still cleans up
                pass
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
