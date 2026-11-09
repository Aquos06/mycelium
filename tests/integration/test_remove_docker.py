"""Real Docker: rpc.sys.remove stops a module, keeps a copy of its data and leaves nothing else of it: no container,
no data volume, no image. On its own stack, so it never touches a running one."""

import shutil
from pathlib import Path

import pytest

from mycelium_sdk import InMemoryBus
from supervisor.registry import MemoryRegistry
from supervisor.service import Supervisor
from tests.integration.test_verify_docker import STACK, _docker_up

REPO = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _docker_up(), reason="no Docker daemon")]


@pytest.fixture(scope="module")
def ops():
    from supervisor.docker_ops import RealDockerOps

    o = RealDockerOps("nats://nowhere:4222", "none", "none", stack=STACK, tz="Asia/Taipei")
    o.ensure_base_image(REPO / "sdk")
    return o


def _run(ops, volume: str, command: str, mode: str = "rw") -> bytes:
    """A shell in a throwaway module-base container with `volume` at /d."""
    return ops.client.containers.run(
        ops.base_image,
        ["sh", "-c", command],
        user="0",
        network_mode="none",
        volumes={volume: {"bind": "/d", "mode": mode}},
        remove=True,
    )


async def test_a_removed_module_leaves_a_copy_of_its_data_and_nothing_else(tmp_path, ops):
    import docker

    grown = tmp_path / "grown"
    (grown / ".git").mkdir(parents=True)
    shutil.copytree(
        REPO / "modules" / "hello", grown / "hello", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache")
    )
    (tmp_path / "modules").mkdir()
    s = Supervisor(
        bus=InMemoryBus(),
        docker=ops,
        registry=MemoryRegistry(),
        modules_dir=tmp_path / "modules",
        sdk_dir=REPO / "sdk",
        grown_dir=grown,
    )
    live, copy = f"{STACK}-data-hello", f"{STACK}-data-hello-v0.1.0-removed-itest"
    try:
        await s.deploy({"name": "hello"})  # no bus to reach: it restarts, as a broken module would
        _run(ops, live, "echo 7 > /d/kept")

        removed = await s.remove({"name": "hello", "label": "v0.1.0-removed-itest"})

        assert (removed.stopped, removed.listed, removed.data) == (True, True, copy)
        assert _run(ops, copy, "cat /d/kept", mode="ro").strip() == b"7"
        with pytest.raises(docker.errors.NotFound):
            ops.client.volumes.get(live)
        with pytest.raises(docker.errors.NotFound):
            ops.client.containers.get(f"{STACK}-mod-hello")
        images = ops.client.images.list(filters={"label": ["mycelium.module=hello", f"mycelium.stack={STACK}"]})
        assert images == []
        assert (await s.list({})).modules == []
    finally:
        ops.stop_module("hello")
        for name in (live, copy):
            try:
                ops.client.volumes.get(name).remove(force=True)
            except docker.errors.NotFound:
                pass
