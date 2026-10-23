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


class ContainerInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    status: str
    image: str


class DockerOps(Protocol):
    def ensure_base_image(self, sdk_dir: Path) -> None: ...
    def build_module(self, module_dir: Path, manifest: Manifest) -> str: ...
    def run_module(self, image: str, manifest: Manifest) -> ContainerInfo: ...
    def stop_module(self, name: str) -> bool: ...
    def logs(self, name: str, tail: int = 100) -> str: ...
    def list_modules(self) -> list[ContainerInfo]: ...


class RealDockerOps:
    def __init__(self, nats_url: str, bus_network: str, internet_network: str, stack: str = "mycelium") -> None:
        import docker  # lazy: unit tests use a fake

        self.client = docker.from_env()
        self.nats_url = nats_url
        self.bus_network = bus_network  # internal network: bus only, no internet
        self.internet_network = internet_network  # attached only when permissions.network
        self.stack = stack
        self.base_image = f"{stack}/module-base:latest"

    def ensure_base_image(self, sdk_dir: Path) -> None:
        log.info("building %s from %s", self.base_image, sdk_dir)
        self.client.images.build(path=str(sdk_dir), tag=self.base_image, rm=True)

    def build_module(self, module_dir: Path, manifest: Manifest) -> str:
        tag = f"{self.stack}/mod-{manifest.name}:{manifest.version}"
        self.client.images.build(
            path=str(module_dir),
            tag=tag,
            rm=True,
            buildargs={"BASE_IMAGE": self.base_image},
            labels={LABEL: manifest.name, STACK_LABEL: self.stack},
        )
        return tag

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
            environment={"NATS_URL": self.nats_url, "MODULE": manifest.name},
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
