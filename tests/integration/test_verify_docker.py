"""Real Docker: rpc.sys.verify runs a module's tests locked down, and a broken module fails.

The probe below runs *inside* the verify container, so the container itself reports what it can reach.
"""

import shutil
from pathlib import Path

import pytest

from mycelium_sdk import InMemoryBus
from supervisor.registry import MemoryRegistry
from supervisor.service import Supervisor

REPO = Path(__file__).resolve().parents[2]
STACK = "mycelium-itest"


def _docker_up() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _docker_up(), reason="no Docker daemon")]

PROBE = """
import os
import socket

import pytest


def test_no_network():
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 53), timeout=2)


def test_nothing_in_the_environment_but_the_time_zone():
    assert "NATS_URL" not in os.environ and "ANTHROPIC_API_KEY" not in os.environ
    assert os.environ["TZ"] == "Asia/Taipei"


def test_only_tmp_is_writable(tmp_path):
    (tmp_path / "ok").write_text("a test's own files are fine")
    with pytest.raises(OSError):
        open("/app/written", "w")
"""


@pytest.fixture(scope="module")
def ops():
    from supervisor.docker_ops import RealDockerOps

    o = RealDockerOps("nats://nowhere:4222", "none", "none", stack=STACK, tz="Asia/Taipei")
    o.ensure_base_image(REPO / "sdk")
    return o


async def test_hello_passes_locked_down_and_a_broken_copy_fails(tmp_path, ops):
    grown = tmp_path / "grown"
    (grown / ".git").mkdir(parents=True)
    staged = grown / ".staging" / "hello"
    shutil.copytree(REPO / "modules" / "hello", staged, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    (staged / "tests" / "test_sandbox.py").write_text(PROBE)
    (tmp_path / "modules").mkdir()
    s = Supervisor(
        bus=InMemoryBus(),
        docker=ops,
        registry=MemoryRegistry(),
        modules_dir=tmp_path / "modules",
        sdk_dir=REPO / "sdk",
        grown_dir=grown,
        verify_timeout=120,
    )

    ok = await s.verify({"name": "hello", "staging": True})
    assert ok["passed"], ok["output"]
    assert "9 passed" in ok["output"]  # hello's six and the three probes

    (staged / "tests" / "test_broken.py").write_text("def test_total():\n    assert 0 == 350\n")
    bad = await s.verify({"name": "hello", "staging": True})
    assert not bad["passed"] and bad["exit_code"] == 1 and "assert 0 == 350" in bad["output"]
    assert not ops.client.images.list(name=f"{STACK}/mod-hello")  # the verify image is gone each time
