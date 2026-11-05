import shutil
from pathlib import Path

import pytest
import yaml

from mycelium_sdk import InMemoryBus, validate_manifest
from supervisor.docker_ops import ContainerInfo, TestRun
from supervisor.registry import MemoryRegistry
from supervisor.service import Supervisor


class FakeDocker:
    def __init__(self, fail_build: bool = False, tests: TestRun | None = None):
        self.fail_build = fail_build
        self.tests = tests or TestRun(exit_code=0, output="3 passed")
        self.running: dict[str, ContainerInfo] = {}
        self.calls: list[str] = []
        self.built_from: list = []

    def ensure_base_image(self, sdk_dir):
        self.calls.append("base")

    def build_module(self, module_dir, manifest, verify=False):
        self.calls.append(f"build:{manifest.name}{':verify' if verify else ''}")
        self.built_from.append(module_dir)
        if self.fail_build:
            raise RuntimeError("build exploded")
        return f"mycelium/mod-{manifest.name}:{'verify' if verify else manifest.version}"

    def run_tests(self, image, timeout):
        self.calls.append(f"test:{image}")
        return self.tests

    def remove_image(self, image):
        self.calls.append(f"rm:{image}")

    def run_module(self, image, manifest):
        self.calls.append(f"run:{manifest.name}")
        info = ContainerInfo(name=manifest.name, status="running", image=image)
        self.running[manifest.name] = info
        return info

    def stop_module(self, name):
        return self.running.pop(name, None) is not None

    def snapshot_data(self, name, label):
        self.calls.append(f"snapshot:{name}:{label}")
        return None if name == "fresh" else f"mycelium-data-{name}-{label}"

    def logs(self, name, tail=100):
        return f"logs of {name} ({tail})"

    def list_modules(self):
        return list(self.running.values())

    def sweep(self):
        self.calls.append("sweep")
        return 0


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


async def test_start_builds_base_image_and_sweeps_leftovers(sup):
    _, _, docker, _ = sup
    assert docker.calls == ["base", "sweep"]


async def test_deploy_happy_path(sup, tmp_path):
    s, bus, docker, reg = sup
    write_module(tmp_path, "alpha")
    reply = await bus.request("rpc.sys.deploy", {"name": "alpha"})
    assert reply["ok"] is True and reply["status"] == "running"
    assert docker.calls[-2:] == ["build:alpha", "run:alpha"]
    assert reg.rows["alpha"].status == "running"
    assert bus.events("sys.module.deployed")[0][1]["name"] == "alpha"


async def test_list_serves_what_each_request_takes(sup, tmp_path):
    """The manifest's described requests reach rpc.sys.list as they were written: Main reads them to call it."""
    _, bus, _, _ = sup
    add = {"description": "Store one expense.", "params": {"amount": "number", "day": "optional date"}}
    write_module(tmp_path, "alpha", requests={"add": add, "total": "Totals, all time by default."})
    await bus.request("rpc.sys.deploy", {"name": "alpha"})
    manifest = (await bus.request("rpc.sys.list", {}))["modules"][0]["manifest"]
    assert manifest["requests"] == ["add", "total"]
    assert manifest["request_specs"]["add"] == {**add, "returns": {}}
    assert manifest["request_specs"]["total"]["description"] == "Totals, all time by default."


@pytest.mark.parametrize("name", ["../etc", "Bad", "", None, 42, "sys", ".staging"])
async def test_deploy_rejects_bad_names(sup, name):
    _, bus, docker, _ = sup
    reply = await bus.request("rpc.sys.deploy", {"name": name})
    assert reply["ok"] is False
    assert docker.calls == ["base", "sweep"]  # nothing built, nothing run


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
    assert reg.rows["omega"].status == "failed"
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


@pytest.mark.parametrize(
    "subject, payload, error",
    [
        ("rpc.sys.deploy", {}, "name: Field required"),
        ("rpc.sys.stop", {"name": "../x"}, "name: Value error, invalid module name: '../x'"),
        ("rpc.sys.verify", {"name": ".staging", "staging": True}, "invalid module name: '.staging'"),
        ("rpc.sys.logs", {"name": "alpha", "tail": "lots"}, "tail: Input should be a valid integer"),
        ("rpc.sys.agent", {"agent": "opencode", "name": "alpha"}, "prompt: Field required"),
    ],
)
async def test_a_request_that_does_not_fit_its_schema_is_refused_by_field(sup, subject, payload, error):
    _, bus, docker, reg = sup
    reply = await bus.request(subject, payload)
    assert reply["ok"] is False and error in reply["error"], reply
    assert docker.calls == ["base", "sweep"] and reg.rows == {}  # refused before anything ran


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
    assert reg.rows["alpha"].status == "retired"
    assert reg.rows["beta"].status == "stopped"  # stopped modules stay stopped
    assert docker.calls == ["build:gamma", "run:gamma"]
    assert bus.events("sys.reconciled")


# ---- two roots, verify ------------------------------------------------------------------------------


def grown(tmp_path: Path, repo: bool = True) -> Path:
    """GROWN_DIR as the builder leaves it: a git repo (a bare .git folder is enough for the supervisor)."""
    g = tmp_path / "grown"
    (g / ".git" if repo else g).mkdir(parents=True)
    return g


async def two_roots(tmp_path, docker=None, repo=True):
    bus, reg, docker = InMemoryBus(), MemoryRegistry(), docker or FakeDocker()
    modules, g = tmp_path / "modules", grown(tmp_path, repo)
    modules.mkdir()
    s = Supervisor(bus=bus, docker=docker, registry=reg, modules_dir=modules, sdk_dir=tmp_path, grown_dir=g)
    await s.start(build_base=False)
    return s, bus, docker, reg, modules, g


async def test_deploys_from_either_root_but_refuses_a_name_in_both(tmp_path):
    _, bus, docker, _, modules, g = await two_roots(tmp_path)
    write_module(modules, "hello")
    write_module(g, "expenses")
    assert (await bus.request("rpc.sys.deploy", {"name": "hello"}))["ok"] is True
    assert (await bus.request("rpc.sys.deploy", {"name": "expenses"}))["ok"] is True
    assert docker.built_from == [(modules / "hello").resolve(), (g / "expenses").resolve()]

    write_module(g, "hello")  # which one would run? neither: say so
    reply = await bus.request("rpc.sys.deploy", {"name": "hello"})
    assert reply["ok"] is False and "more than one place" in reply["error"]


async def test_a_staged_build_is_verified_in_its_own_image_and_never_deployed(tmp_path):
    _, bus, docker, reg, _, g = await two_roots(tmp_path)
    write_module(g / ".staging", "expenses")

    reply = await bus.request("rpc.sys.verify", {"name": "expenses", "staging": True})
    assert reply["ok"] is True and reply["passed"] is True and reply["stage"] == "tests"
    assert reply["output"] == "3 passed" and reply["exit_code"] == 0
    image = "mycelium/mod-expenses:verify"
    assert docker.calls == ["build:expenses:verify", f"test:{image}", f"rm:{image}"]
    assert docker.built_from == [(g / ".staging" / "expenses").resolve()]
    assert reg.rows == {} and bus.events("sys.module.deployed") == []  # verify deploys nothing

    reply = await bus.request("rpc.sys.deploy", {"name": "expenses"})  # still only staged
    assert reply["ok"] is False and "no module folder" in reply["error"]


async def test_verify_reports_failing_tests_with_their_output(tmp_path):
    failing = FakeDocker(tests=TestRun(exit_code=1, output="FAILED tests/test_x.py::test_total - assert 0 == 350"))
    _, bus, docker, _, modules, _ = await two_roots(tmp_path, failing)
    write_module(modules, "hello")  # a deployed module can be re-verified too
    reply = await bus.request("rpc.sys.verify", {"name": "hello"})
    assert reply["ok"] is True and reply["passed"] is False and reply["exit_code"] == 1
    assert "assert 0 == 350" in reply["output"]
    assert docker.calls[-1] == "rm:mycelium/mod-hello:verify"  # the image goes either way


async def test_verify_says_when_the_tests_ran_out_of_time(tmp_path):
    slow = FakeDocker(tests=TestRun(exit_code=-1, output="", timed_out=True))
    _, bus, _, _, modules, _ = await two_roots(tmp_path, slow)
    write_module(modules, "hello")
    reply = await bus.request("rpc.sys.verify", {"name": "hello"})
    assert reply["passed"] is False and reply["timed_out"] is True


async def test_verify_reports_an_image_that_does_not_build_as_a_failure_not_an_error(tmp_path):
    _, bus, docker, _, _, g = await two_roots(tmp_path, FakeDocker(fail_build=True))
    write_module(g / ".staging", "expenses")
    reply = await bus.request("rpc.sys.verify", {"name": "expenses", "staging": True})
    assert reply["ok"] is True and reply["passed"] is False and reply["stage"] == "build"
    assert "build exploded" in reply["output"] and reply["exit_code"] is None
    assert docker.calls == ["build:expenses:verify"]  # nothing ran, nothing to remove


async def test_verify_refuses_what_it_cannot_find_or_trust(tmp_path, sup):
    _, bus, docker, _, _, g = await two_roots(tmp_path)
    reply = await bus.request("rpc.sys.verify", {"name": "expenses", "staging": True})
    assert reply["ok"] is False and "nothing staged" in reply["error"]
    d = write_module(g / ".staging", "expenses")
    (d / "manifest.yaml").write_text(yaml.safe_dump({"name": "other", "purpose": "A test module that does a thing."}))
    reply = await bus.request("rpc.sys.verify", {"name": "expenses", "staging": True})
    assert reply["ok"] is False and "manifest.name" in reply["error"]
    assert docker.calls == []

    _, no_grown, _, _ = sup  # no GROWN_DIR: nothing is ever staged
    reply = await no_grown.request("rpc.sys.verify", {"name": "expenses", "staging": True})
    assert reply["ok"] is False and "GROWN_DIR" in reply["error"]


async def test_reconcile_keeps_modules_when_the_grown_root_is_not_mounted(tmp_path):
    s, _, _, reg, _, _ = await two_roots(tmp_path, repo=False)  # the empty folder Docker makes for a missing mount
    await reg.upsert(validate_manifest({"name": "expenses", "purpose": "Tracks what Hansen spends."}), "running", "x")
    assert await s.reconcile() == {"expenses": "kept (a modules root is not mounted)"}
    assert reg.rows["expenses"].status == "running"  # it comes back when the root does


async def test_reconcile_retires_a_grown_module_whose_folder_is_gone_from_the_repo(tmp_path):
    s, _, _, reg, _, _ = await two_roots(tmp_path)
    await reg.upsert(validate_manifest({"name": "expenses", "purpose": "Tracks what Hansen spends."}), "running", "x")
    assert await s.reconcile() == {"expenses": "retired (folder gone)"}


# ---- the real Docker wrapper, against a recording client -----------------------------------------


class RecordingContainer:
    def __init__(self, wait=None):
        self._wait = wait
        self.status = "running"
        self.killed = self.removed = False

    def wait(self, timeout):
        if isinstance(self._wait, Exception):
            raise self._wait
        return self._wait or {"StatusCode": 0}

    def kill(self):
        self.killed = True

    def logs(self, **_):
        return b"..... 5 passed in 0.4s"

    def remove(self, force=False):
        self.removed = force

    def reload(self):
        pass


class RecordingClient:
    def __init__(self, container):
        self.container = container
        self.runs: list[dict] = []
        self.containers = self
        self.images = self

    def run(self, image, **kwargs):  # containers.run
        self.runs.append({"image": image, **kwargs})
        return self.container

    def get(self, name):  # containers.get, from stop_module before a run
        import docker

        raise docker.errors.NotFound("none")

    def remove(self, image, force=False):  # images.remove
        self.removed_image = image


def real_ops(monkeypatch, container):
    import docker

    from supervisor.docker_ops import RealDockerOps

    client = RecordingClient(container)
    monkeypatch.setattr(docker, "from_env", lambda: client)
    return RealDockerOps("nats://nats:4222", "bus", "internet", stack="mycelium-dev", tz="Asia/Taipei"), client


def test_real_docker_runs_tests_locked_down(monkeypatch):
    ops, client = real_ops(monkeypatch, RecordingContainer())
    run = ops.run_tests("mycelium-dev/mod-expenses:verify", timeout=60)
    assert run.passed and run.output.endswith("5 passed in 0.4s")
    kw = client.runs[0]
    assert kw["network_mode"] == "none" and "network" not in kw
    assert kw["environment"] == {"TZ": "Asia/Taipei", "PYTHONDONTWRITEBYTECODE": "1"}  # no NATS_URL, no keys
    assert kw["read_only"] is True and kw["cap_drop"] == ["ALL"] and kw["security_opt"] == ["no-new-privileges"]
    assert kw["labels"] == {"mycelium.verify": "mycelium-dev"}  # the stack, so only this stack sweeps it
    assert kw["pids_limit"] == 256 and kw["mem_limit"] == "512m" and "/tmp" in kw["tmpfs"]
    assert "mycelium.stack" not in kw["labels"]  # never listed as a module
    assert client.container.removed is True


def test_real_docker_kills_tests_that_run_too_long(monkeypatch):
    ops, client = real_ops(monkeypatch, RecordingContainer(wait=TimeoutError("read timed out")))
    run = ops.run_tests("mycelium-dev/mod-expenses:verify", timeout=1)
    assert run.timed_out and not run.passed and client.container.killed and client.container.removed


def test_real_docker_gives_every_module_the_users_time_zone(monkeypatch):
    ops, client = real_ops(monkeypatch, RecordingContainer())
    ops.run_module("mycelium-dev/mod-hello:0.1.0", validate_manifest({"name": "hello", "purpose": "Counts chats."}))
    assert client.runs[0]["environment"]["TZ"] == "Asia/Taipei"


async def test_list_names_every_module_folder_in_both_roots(tmp_path):
    grown = tmp_path / "grown"
    (grown / ".git").mkdir(parents=True)
    write_module(tmp_path / "modules", "hello")
    write_module(grown, "expenses")
    (grown / ".staging" / "wip").mkdir(parents=True)
    s = Supervisor(
        bus=InMemoryBus(),
        docker=FakeDocker(),
        registry=MemoryRegistry(),
        modules_dir=tmp_path / "modules",
        sdk_dir=tmp_path,
        grown_dir=grown,
    )
    reply = await s.list({})
    assert reply.modules == [] and reply.folders == ["expenses", "hello"]
    assert reply.grown == ["expenses"]  # what the builder can change: not hello, not a build in .staging


async def test_a_snapshot_copies_a_modules_data_before_a_change(sup):
    _, bus, docker, _ = sup
    reply = await bus.request("rpc.sys.snapshot", {"name": "expenses", "label": "v0.1.0-001a2b"})
    assert reply == {"ok": True, "name": "expenses", "volume": "mycelium-data-expenses-v0.1.0-001a2b"}
    assert docker.calls[-1] == "snapshot:expenses:v0.1.0-001a2b"
    fresh = await bus.request("rpc.sys.snapshot", {"name": "fresh", "label": "v0.1.0-001a2b"})
    assert fresh["ok"] is True and fresh["volume"] is None  # no data yet: nothing to keep


@pytest.mark.parametrize(
    "data",
    [{"name": "../etc", "label": "v1"}, {"name": "expenses", "label": "../x"}, {"name": "expenses", "label": "a b"}],
)
async def test_a_snapshot_takes_only_a_module_name_and_a_plain_label(sup, data):
    _, bus, docker, _ = sup
    assert (await bus.request("rpc.sys.snapshot", data))["ok"] is False
    assert not any(c.startswith("snapshot:") for c in docker.calls)


class VolumeClient:
    """Docker's volumes and containers, as snapshot_data uses them: the module's volume, its container (running,
    so it is paused while the copy runs), and the copy container's run."""

    def __init__(self, has_data=True, copy_fails=False):
        self.has_data, self.copy_fails = has_data, copy_fails
        self.created: list[tuple[str, dict]] = []
        self.removed: list[str] = []
        self.runs: list[dict] = []
        self.paused: list[str] = []
        self.volumes = self
        self.containers = self

    # volumes.get / volumes.create, and the volume a get returns
    def create(self, name, labels):
        self.created.append((name, labels))

    def get(self, name):
        import docker

        if name.startswith("mycelium-dev-mod-"):  # containers.get
            client = self

            class Running:
                status = "running"

                def pause(self):
                    client.paused.append("pause")

                def unpause(self):
                    client.paused.append("unpause")

            return Running()
        if name == "mycelium-dev-data-expenses" and not self.has_data:
            raise docker.errors.NotFound("no volume")
        client = self

        class Volume:
            def remove(self, force=False):
                client.removed.append(name)

        return Volume()

    def run(self, image, command, **kw):  # containers.run
        self.runs.append({"image": image, "command": command, **kw})
        if self.copy_fails:
            raise RuntimeError("cp: no space left on device")


def volume_ops(monkeypatch, client):
    import docker

    from supervisor.docker_ops import RealDockerOps

    monkeypatch.setattr(docker, "from_env", lambda: client)
    return RealDockerOps("nats://nats:4222", "bus", "internet", stack="mycelium-dev", tz="Asia/Taipei")


def test_real_docker_copies_the_data_volume_with_the_module_paused(monkeypatch):
    client = VolumeClient()
    volume = volume_ops(monkeypatch, client).snapshot_data("expenses", "v0.1.0-001a2b")
    assert volume == "mycelium-dev-data-expenses-v0.1.0-001a2b"
    assert client.created == [(volume, {"mycelium.data": "expenses", "mycelium.stack": "mycelium-dev"})]
    (run,) = client.runs
    assert run["image"] == "mycelium-dev/module-base:latest" and run["command"] == ["sh", "-c", "cp -a /from/. /to/"]
    assert run["volumes"] == {
        "mycelium-dev-data-expenses": {"bind": "/from", "mode": "ro"},
        volume: {"bind": "/to", "mode": "rw"},
    }
    assert run["network_mode"] == "none" and run["remove"] is True and run["user"] == "0"
    assert client.paused == ["pause", "unpause"]


def test_real_docker_keeps_no_half_copy_and_unpauses_the_module(monkeypatch):
    client = VolumeClient(copy_fails=True)
    with pytest.raises(RuntimeError, match="no space"):
        volume_ops(monkeypatch, client).snapshot_data("expenses", "v0.1.0-001a2b")
    assert client.removed == ["mycelium-dev-data-expenses-v0.1.0-001a2b"] and client.paused == ["pause", "unpause"]


def test_real_docker_has_nothing_to_copy_for_a_module_without_data(monkeypatch):
    client = VolumeClient(has_data=False)
    assert volume_ops(monkeypatch, client).snapshot_data("expenses", "v0.1.0-001a2b") is None
    assert client.created == [] and client.runs == []
