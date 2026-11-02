"""Coding agents in the supervisor: the recipes, what goes into an agent's container and what comes back out,
keys redacted, and the container's settings."""

import io
import json
import tarfile
from pathlib import Path

import pytest

from mycelium_sdk import InMemoryBus
from supervisor.agents import SKIPPED_MAX, TOTAL_MAX, load_recipes, pack, redact, secrets, unpack
from supervisor.docker_ops import AgentResult
from supervisor.registry import MemoryRegistry
from supervisor.service import Supervisor
from tests.unit.test_supervisor import FakeDocker, RecordingClient, RecordingContainer, real_ops

AGENTS_DIR = Path(__file__).resolve().parents[2] / "services" / "supervisor" / "agent_images"
KEY = "sk-ant-api03-very-secret"


def tar_of(files: dict[str, str | bytes], links: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, text in files.items():
            data = text.encode() if isinstance(text, str) else text
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type, info.linkname = tarfile.SYMTYPE, target
            tar.addfile(info)
    return buf.getvalue()


LEFT = tar_of(
    {
        "module/app/main.py": f"KEY = '{KEY}'\n",
        "module/tests/test_notes.py": "def test_x(): pass\n",
        "module/manifest.yaml": "purpose: x\n",
        "module/node_modules/x/index.js": "x",
        "module/.opencode/state.md": "x",
        "module/app/__pycache__/main.cpython-312.pyc": b"\x00",
        "module/app/big.py": "x" * 70_000,
        "module/app/blob.bin": b"\x00\x01",
        "PROMPT.md": "not the module",
    },
    links={"module/app/link.py": "/etc/hosts"},
)


class AgentDocker(FakeDocker):
    def __init__(self, result: AgentResult | None = None):
        super().__init__()
        self.result = result or AgentResult(exit_code=0, output=f"done; key was {KEY}", archive=LEFT)
        self.agent_runs: list[dict] = []

    def build_agent_image(self, name, context):
        self.calls.append(f"agent-image:{name}")
        self.built_from.append(context)
        return f"mycelium/coder-{name}:latest"

    def run_agent(self, image, work, env, timeout, memory_mb, cpus):
        self.agent_runs.append(
            {"image": image, "work": work, "env": env, "timeout": timeout, "memory_mb": memory_mb, "cpus": cpus}
        )
        return self.result


ENV = {
    "AGENT_ENDPOINT": "http://192.168.0.107:8000/v1",
    "AGENT_MODEL": "/model",
    "ANTHROPIC_API_KEY": KEY,
    "MODULE_TZ": "Asia/Taipei",
    "NATS_URL": "nats://nats:4222",
    "DATABASE_URL": "postgresql://mycelium:secret@postgres/mycelium",
}


def make(tmp_path, env=None, docker=None, timeout=3600.0):
    grown = tmp_path / "grown"
    (grown / ".git").mkdir(parents=True)
    staged = grown / ".staging" / "notes"
    (staged / "app").mkdir(parents=True)
    (staged / "app" / "main.py").write_text("print('hi')\n")
    (staged / "manifest.yaml").write_text("name: notes\n")
    (staged / "app" / "__pycache__").mkdir()
    (staged / "app" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (tmp_path / "modules").mkdir()
    docker = docker or AgentDocker()
    sup = Supervisor(
        bus=InMemoryBus(),
        docker=docker,
        registry=MemoryRegistry(),
        modules_dir=tmp_path / "modules",
        sdk_dir=tmp_path,
        grown_dir=grown,
        agents=load_recipes(AGENTS_DIR / "agents.yaml"),
        agents_dir=AGENTS_DIR,
        agent_timeout=timeout,
        env=ENV if env is None else env,
    )
    return sup, docker


def test_every_agent_has_an_image_folder_and_a_start_script():
    recipes = load_recipes(AGENTS_DIR / "agents.yaml")
    assert set(recipes) == {"opencode", "codex", "aider", "claude_code"}
    for name in recipes:
        dockerfile = (AGENTS_DIR / name / "Dockerfile").read_text()
        assert "FROM ${BASE_IMAGE}" in dockerfile and "USER module" in dockerfile
        assert (AGENTS_DIR / name / "run.sh").read_text().startswith("#!/bin/sh")


async def test_an_agent_works_on_a_copy_with_only_its_own_variables(tmp_path):
    sup, docker = make(tmp_path)
    out = await sup.agent({"agent": "claude_code", "name": "notes", "prompt": "write the module", "timeout": 600})

    run = docker.agent_runs[0]
    assert docker.built_from == [AGENTS_DIR / "claude_code"]
    assert run["env"] == {"ANTHROPIC_API_KEY": KEY, "MODULE_NAME": "notes", "TZ": "Asia/Taipei", "HOME": "/home/module"}
    assert run["timeout"] == 600 and run["memory_mb"] == 2048
    with tarfile.open(fileobj=io.BytesIO(run["work"])) as tar:
        names = {m.name: m for m in tar.getmembers()}
        assert tar.extractfile(names["PROMPT.md"]).read() == b"write the module"
        assert tar.extractfile(names["module/app/main.py"]).read() == b"print('hi')\n"
        assert names["module/app/main.py"].uid == 10001
        assert not any("__pycache__" in n for n in names)

    assert out.exit_code == 0 and KEY not in out.output and "[redacted]" in out.output
    assert out.skipped == ["app/big.py"]
    assert out.files == {
        "app/main.py": "KEY = '[redacted]'\n",
        "tests/test_notes.py": "def test_x(): pass\n",
        "manifest.yaml": "purpose: x\n",
    }


async def test_an_agent_on_your_own_model_gets_the_address_and_never_the_rest(tmp_path):
    sup, docker = make(tmp_path)
    await sup.agent({"agent": "opencode", "name": "notes", "prompt": "go"})
    env = docker.agent_runs[0]["env"]
    assert env["MODEL_ENDPOINT"] == "http://192.168.0.107:8000/v1" and env["MODEL_NAME"] == "/model"
    assert "MODEL_KEY" not in env  # AGENT_KEY unset: left out
    assert not {"ANTHROPIC_API_KEY", "NATS_URL", "DATABASE_URL"} & set(env)
    assert docker.agent_runs[0]["timeout"] == 3600  # no timeout asked: the supervisor's ceiling


@pytest.mark.parametrize(
    "data, env, error",
    [
        ({"agent": "goose", "name": "notes", "prompt": "go"}, ENV, "no agent 'goose'"),
        ({"agent": "opencode", "name": "notes", "prompt": "go"}, {}, "set AGENT_ENDPOINT, AGENT_MODEL"),
        ({"agent": "claude_code", "name": "notes", "prompt": "go"}, {"AGENT_MODEL": "m"}, "set ANTHROPIC_API_KEY"),
        ({"agent": "opencode", "name": "notes", "prompt": " "}, ENV, "prompt is required"),
        ({"agent": "opencode", "name": "other", "prompt": "go"}, ENV, "nothing staged for other"),
        ({"agent": "opencode", "name": "../x", "prompt": "go"}, ENV, "invalid module name"),
    ],
)
async def test_agent_refusals(tmp_path, data, env, error):
    sup, docker = make(tmp_path, env=env)
    with pytest.raises((ValueError, FileNotFoundError), match=error.replace("(", r"\(")):
        await sup.agent(data)
    assert docker.agent_runs == []


async def test_timeouts_are_kept_within_bounds(tmp_path):
    sup, docker = make(tmp_path, timeout=900)
    await sup.agent({"agent": "opencode", "name": "notes", "prompt": "go", "timeout": 99999})
    await sup.agent({"agent": "opencode", "name": "notes", "prompt": "go", "timeout": 1})
    assert [r["timeout"] for r in docker.agent_runs] == [900, 10]
    assert docker.calls.count("agent-image:opencode") == 1  # built once per start, not every round


async def test_list_agents_says_what_each_still_needs(tmp_path):
    sup, _ = make(tmp_path, env={"ANTHROPIC_API_KEY": KEY})
    agents = {a.name: a for a in (await sup.list_agents({})).agents}
    assert agents["claude_code"].ready and agents["claude_code"].reason is None
    assert (
        not agents["opencode"].ready
        and agents["opencode"].reason == "set AGENT_ENDPOINT, AGENT_MODEL for the supervisor"
    )


async def test_the_rpc_answers_on_the_bus(tmp_path):
    sup, _ = make(tmp_path)
    await sup.start(build_base=False)
    reply = await sup.bus.request("rpc.sys.agents", {})
    assert reply["ok"] and len(reply["agents"]) == 4
    reply = await sup.bus.request("rpc.sys.agent", {"agent": "nobody", "name": "notes", "prompt": "x"})
    assert reply == {"ok": False, "error": "no agent 'nobody'; one of opencode, codex, aider, claude_code"}


def test_unpack_takes_small_text_files_only_and_says_what_it_left_out():
    out = unpack(LEFT)
    assert set(out.files) == {"app/main.py", "tests/test_notes.py", "manifest.yaml"}
    assert out.skipped == ["app/big.py"] and out.skipped_more == 0  # text, but too big: there, not deleted
    empty = unpack(tar_of({"module/../escape.py": "x", "other/app.py": "x"}))
    assert empty.files == {} and empty.skipped == []


def test_unpack_keeps_the_reply_under_one_nats_message():
    many = {f"module/app/m{i:02}.py": "x" * 60_000 for i in range(12)}
    out = unpack(tar_of({"module/manifest.yaml": "purpose: x\n", **many}))
    assert "manifest.yaml" in out.files  # the top of the folder first
    assert len(json.dumps(out.files)) <= TOTAL_MAX and len(out.files) + len(out.skipped) == 13


def test_unpack_counts_chinese_text_as_the_bus_sends_it():
    # each file is 54 KB of UTF-8 but 104 KB of JSON (\uXXXX): six pass a byte count (324 KB) and do not fit (624 KB)
    chinese = {f"module/app/m{i}.py": "# 小美推薦的拉麵店\n" * 2_000 for i in range(6)}
    out = unpack(tar_of(chinese))
    assert len(json.dumps(out.files)) <= TOTAL_MAX and out.skipped  # some left out, listed, not lost


def test_unpack_lists_only_so_many_left_out_files_and_counts_the_rest():
    venv = {f"module/venv/lib/m{i:04}.py": "x" * 70_000 for i in range(SKIPPED_MAX + 50)}
    out = unpack(tar_of({"module/app/main.py": "x = 1\n", **venv}))
    assert out.files == {"app/main.py": "x = 1\n"}
    assert len(out.skipped) == SKIPPED_MAX and out.skipped_more == 50


def test_pack_skips_links_and_caches(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("x")
    (tmp_path / "app" / "link.py").symlink_to("/etc/hosts")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "v").write_text("x")
    with tarfile.open(fileobj=io.BytesIO(pack(tmp_path, "task"))) as tar:
        assert sorted(tar.getnames()) == ["PROMPT.md", "module", "module/app", "module/app/main.py"]


def test_secrets_are_key_and_token_values():
    env = {"MODEL_KEY": "none", "ANTHROPIC_API_KEY": KEY, "GH_TOKEN": "ghp_1234567890", "MODEL_NAME": "/model-long"}
    assert secrets(env) == [KEY, "ghp_1234567890"]
    assert redact(f"a {KEY} b", [KEY]) == "a [redacted] b"


def test_real_docker_runs_an_agent_without_the_mesh(monkeypatch):
    class AgentContainer(RecordingContainer):
        def __init__(self):
            super().__init__()
            self.put = self.started = None

        def put_archive(self, path, data):
            self.put = (path, data)

        def start(self):
            self.started = True

        def get_archive(self, path):
            return [LEFT[:100], LEFT[100:]], {"name": "module"}

    class AgentClient(RecordingClient):
        def create(self, image, **kwargs):  # containers.create
            self.runs.append({"image": image, **kwargs})
            return self.container

    container = AgentContainer()
    ops, _ = real_ops(monkeypatch, container)
    client = AgentClient(container)
    ops.client = client
    result = ops.run_agent("img", b"tar", {"MODEL_NAME": "m"}, 60, 2048, 2.0)

    kw = client.runs[0]
    assert kw["network_mode"] == "bridge" and kw["environment"] == {"MODEL_NAME": "m"}
    assert kw["cap_drop"] == ["ALL"] and kw["security_opt"] == ["no-new-privileges"]
    assert kw["mem_limit"] == "2048m" and kw["nano_cpus"] == 2_000_000_000 and kw["pids_limit"] == 512
    assert kw["labels"] == {"mycelium.agent": "mycelium-dev"}  # the stack, so only this stack sweeps it
    assert container.put == ("/work", b"tar") and container.started and container.removed
    assert result.archive == LEFT and result.exit_code == 0


async def test_start_sweeps_what_a_restart_left_behind(tmp_path):
    sup, docker = make(tmp_path)
    await sup.start()
    assert docker.calls[:2] == ["base", "sweep"]


def test_verify_and_agent_images_never_look_like_modules(monkeypatch):
    from mycelium_sdk import validate_manifest

    built = []

    class BuildClient(RecordingClient):
        def build(self, **kwargs):  # images.build
            built.append(kwargs)

    ops, _ = real_ops(monkeypatch, RecordingContainer())
    ops.client = BuildClient(RecordingContainer())
    manifest = validate_manifest({"name": "notes", "purpose": "Keeps the last note from chat."})
    ops.build_module(Path("/x"), manifest, verify=True)
    ops.build_agent_image("opencode", Path("/y"))
    ops.build_module(Path("/x"), manifest)
    assert built[0]["labels"] == {"mycelium.verify": "notes"} and built[0]["tag"].endswith(":verify")
    assert built[1]["labels"] == {"mycelium.agent": "opencode"}
    assert built[2]["labels"] == {"mycelium.module": "notes", "mycelium.stack": "mycelium-dev"}


def test_sweep_removes_only_this_stacks_leftovers_and_never_stops_the_start(monkeypatch):
    class Leftover:
        def __init__(self, name, labels, fails=False):
            self.name, self.labels, self.fails, self.removed = name, labels, fails, False

        def remove(self, force=False):
            if self.fails:
                raise RuntimeError("removal of container already in progress")
            self.removed = force

    leftovers = [
        Leftover("ours", {"mycelium.verify": "mycelium-dev"}),
        Leftover("ours-before", {"mycelium.agent": "mycelium-dev/coder-opencode:latest"}),  # the label of old
        Leftover("ours-stuck", {"mycelium.verify": "mycelium-dev"}, fails=True),
        Leftover("production", {"mycelium.verify": "mycelium"}),
        Leftover("production-agent", {"mycelium.agent": "mycelium/coder-opencode:latest"}),
    ]

    class SweepClient(RecordingClient):
        def list(self, all=False, filters=None):  # containers.list, by label key
            return [c for c in leftovers if filters["label"] in c.labels]

    ops, _ = real_ops(monkeypatch, RecordingContainer())
    ops.client = SweepClient(RecordingContainer())
    assert ops.sweep() == 2  # the stuck one is logged and left; the supervisor still starts
    assert [c.name for c in leftovers if c.removed] == ["ours", "ours-before"]


async def test_a_reply_too_big_to_send_is_answered_with_an_error(tmp_path):
    sup, _ = make(tmp_path)
    sent = []

    async def responder(payload):
        if payload.get("ok"):
            raise RuntimeError("maximum payload exceeded")
        sent.append(payload)

    from mycelium_sdk import Message

    msg = Message(subject="rpc.sys.agents", data={}, reply="_INBOX.x", responder=responder)
    await sup._wrap(sup.list_agents)(msg)
    assert sent == [{"ok": False, "error": "the reply could not be sent: RuntimeError: maximum payload exceeded"}]
