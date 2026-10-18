import shutil
from pathlib import Path

import pytest
import yaml

from mycelium_sdk import InMemoryBus, validate_manifest
from supervisor.app import Supervisor
from supervisor.docker_ops import ContainerInfo
from supervisor.registry import MemoryRegistry


class FakeDocker:
    def __init__(self, fail_build: bool = False):
        self.fail_build = fail_build
        self.running: dict[str, ContainerInfo] = {}
        self.calls: list[str] = []

    def ensure_base_image(self, sdk_dir):
        self.calls.append("base")

    def build_module(self, module_dir, manifest):
        self.calls.append(f"build:{manifest.name}")
        if self.fail_build:
            raise RuntimeError("build exploded")
        return f"mycelium/mod-{manifest.name}:{manifest.version}"

    def run_module(self, image, manifest):
        self.calls.append(f"run:{manifest.name}")
        info = ContainerInfo(name=manifest.name, status="running", image=image)
        self.running[manifest.name] = info
        return info

    def stop_module(self, name):
        return self.running.pop(name, None) is not None

    def logs(self, name, tail=100):
        return f"logs of {name} ({tail})"

    def list_modules(self):
        return list(self.running.values())


def write_module(root: Path, name: str, **over) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "manifest.yaml").write_text(
        yaml.safe_dump({"name": name, "purpose": "A test module that does a thing.", **over})
    )
    return d


@pytest.fixture
async def sup(tmp_path):
    bus = InMemoryBus()
    docker = FakeDocker()
    reg = MemoryRegistry()
    s = Supervisor(bus=bus, docker=docker, registry=reg, modules_dir=tmp_path, sdk_dir=tmp_path)
    await s.start()
    return s, bus, docker, reg


async def test_start_builds_base_image(sup):
    _, _, docker, _ = sup
    assert docker.calls == ["base"]


async def test_deploy_happy_path(sup, tmp_path):
    s, bus, docker, reg = sup
    write_module(tmp_path, "alpha")
    reply = await bus.request("rpc.sys.deploy", {"name": "alpha"})
    assert reply["ok"] is True and reply["status"] == "running"
    assert docker.calls[-2:] == ["build:alpha", "run:alpha"]
    assert reg.rows["alpha"]["status"] == "running"
    assert bus.events("sys.module.deployed")[0][1]["name"] == "alpha"


@pytest.mark.parametrize("name", ["../etc", "Bad", "", None, 42, "sys"])
async def test_deploy_rejects_bad_names(sup, name):
    _, bus, docker, _ = sup
    reply = await bus.request("rpc.sys.deploy", {"name": name})
    assert reply["ok"] is False
    assert docker.calls == ["base"]


async def test_deploy_missing_folder(sup):
    _, bus, _, _ = sup
    reply = await bus.request("rpc.sys.deploy", {"name": "ghost"})
    assert reply["ok"] is False and "no module folder" in reply["error"]


async def test_deploy_invalid_manifest(sup, tmp_path):
    _, bus, docker, _ = sup
    write_module(tmp_path, "beta", subscribes=[">"])
    reply = await bus.request("rpc.sys.deploy", {"name": "beta"})
    assert reply["ok"] is False
    assert "build:beta" not in docker.calls


async def test_folder_and_manifest_name_must_match(sup, tmp_path):
    _, bus, _, _ = sup
    d = tmp_path / "gamma"
    d.mkdir()
    (d / "manifest.yaml").write_text(yaml.safe_dump({"name": "delta", "purpose": "Mismatched name test."}))
    reply = await bus.request("rpc.sys.deploy", {"name": "gamma"})
    assert reply["ok"] is False and "manifest.name" in reply["error"]


async def test_actuation_needs_approval(sup, tmp_path):
    s, bus, _, _ = sup
    write_module(tmp_path, "lights", permissions={"actuation": True})
    denied = await bus.request("rpc.sys.deploy", {"name": "lights"})
    assert denied["ok"] is False and "APPROVED_ACTUATORS" in denied["error"]
    s.approved_actuators.add("lights")
    assert (await bus.request("rpc.sys.deploy", {"name": "lights"}))["ok"] is True


async def test_build_failure_marks_failed(tmp_path):
    bus, reg = InMemoryBus(), MemoryRegistry()
    s = Supervisor(bus=bus, docker=FakeDocker(fail_build=True), registry=reg, modules_dir=tmp_path, sdk_dir=tmp_path)
    await s.start(build_base=False)
    write_module(tmp_path, "omega")
    reply = await bus.request("rpc.sys.deploy", {"name": "omega"})
    assert reply["ok"] is False and "build exploded" in reply["error"]
    assert reg.rows["omega"]["status"] == "failed"
    assert bus.events("sys.module.failed")


async def test_stop_list_logs(sup, tmp_path):
    _, bus, _, _ = sup
    write_module(tmp_path, "alpha")
    await bus.request("rpc.sys.deploy", {"name": "alpha"})
    listed = await bus.request("rpc.sys.list", {})
    assert listed["modules"][0]["container"] == "running"
    logs = await bus.request("rpc.sys.logs", {"name": "alpha", "tail": 5})
    assert logs["logs"] == "logs of alpha (5)"
    stopped = await bus.request("rpc.sys.stop", {"name": "alpha"})
    assert stopped["stopped"] is True
    assert (await bus.request("rpc.sys.list", {}))["modules"][0]["status"] == "stopped"


async def test_health_pings_modules(sup, tmp_path):
    _, bus, _, _ = sup
    write_module(tmp_path, "alpha")
    await bus.request("rpc.sys.deploy", {"name": "alpha"})

    async def health(msg):
        await msg.respond({"ok": True})

    await bus.subscribe("rpc.mod.alpha.health", health)
    reply = await bus.request("rpc.sys.health", {})
    assert reply["modules"]["alpha"] == {"ok": True}


async def test_reconcile_redeploys_running_and_retires_missing(tmp_path):
    bus, reg, docker = InMemoryBus(), MemoryRegistry(), FakeDocker()
    s = Supervisor(bus=bus, docker=docker, registry=reg, modules_dir=tmp_path, sdk_dir=tmp_path)
    await s.start(build_base=False)
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    await bus.request("rpc.sys.deploy", {"name": "alpha"})
    await bus.request("rpc.sys.deploy", {"name": "beta"})
    await bus.request("rpc.sys.stop", {"name": "beta"})
    # alpha's folder disappears, plus a registry row for a module that was running elsewhere
    shutil.rmtree(tmp_path / "alpha")
    write_module(tmp_path, "gamma")
    await reg.upsert(
        validate_manifest({"name": "gamma", "purpose": "Running before restart."}),
        "running",
        "old",
    )
    docker.calls.clear()

    results = await s.reconcile()
    assert results == {"alpha": "retired (folder gone)", "gamma": "redeployed"}
    assert reg.rows["alpha"]["status"] == "retired"
    assert reg.rows["beta"]["status"] == "stopped"  # stopped modules stay stopped
    assert docker.calls == ["build:gamma", "run:gamma"]
    assert bus.events("sys.reconciled")
