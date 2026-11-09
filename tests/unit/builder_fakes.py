"""What the builder's tests share: a small module that works, a coder that writes what it is told, and a
supervisor that answers verify by running pytest on the staged folder (no Docker), plus deploy, snapshot, remove
and list."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from builder.coders.base import CoderError
from builder.pipeline import Pipeline
from builder.prompts import Brief
from builder.repo import GrownRepo
from builder.schemas import CoderContext, CoderResult
from builder.workspace import Workspace, write_file
from mycelium_sdk import InMemoryBus

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "template"
EXAMPLE = REPO / "modules" / "hello"
SPEC = "# Spec: notes\n\nKeep the last chat message that starts with 'note ' and give it back on request.\n"

MANIFEST = """\
purpose: Keeps the last note from chat so it can be read back.
subscribes: [sense.chat]
emits: [note.kept]
requests:
  last:
    description: The last note kept from chat.
    returns: {note: string}
permissions: {network: true, actuation: true}
"""

CODE = """\
from mycelium_sdk import Module


def build(**kwargs) -> Module:
    mod = Module(**kwargs)
    state = {"last": ""}

    @mod.on("sense.chat")
    async def on_chat(msg):
        text = msg.data.get("text", "")
        if text.startswith("note "):
            state["last"] = text[5:]
            await mod.emit("note.kept", {"text": state["last"]})

    @mod.on_request("last")
    async def last(data):
        return {"text": state["last"]}

    return mod


if __name__ == "__main__":
    build().run()
"""

TESTS = """\
from pathlib import Path

from app.main import build
from mycelium_sdk import InMemoryBus

ROOT = Path(__file__).resolve().parents[1]


async def test_keeps_a_note(tmp_path):
    bus = InMemoryBus()
    mod = build(manifest_path=ROOT / "manifest.yaml", bus=bus, data_dir=tmp_path)
    await mod.start()
    await bus.publish("sense.chat", {"text": "note buy milk"})
    assert (await bus.request("rpc.mod.notes.last", {}))["text"] == "WANT"
    await mod.stop()
"""

GOOD = {"manifest.yaml": MANIFEST, "app/main.py": CODE, "tests/test_notes.py": TESTS.replace("WANT", "buy milk")}
BROKEN = {**GOOD, "tests/test_notes.py": TESTS.replace("WANT", "buy bread")}


def brief() -> Brief:
    return Brief.load(TEMPLATE, EXAMPLE)


class FakeCoder:
    """Writes the files of round n (the last entry repeats); an Exception in the list is raised instead."""

    name = "fake"

    def __init__(self, rounds: list[dict[str, str] | Exception], reason: str | None = None) -> None:
        self.rounds = rounds
        self.reason = reason
        self.seen: list[CoderContext] = []
        self.gate: asyncio.Event | None = None  # set it to hold a build until the test lets it go

    async def ready(self) -> str | None:
        return self.reason

    async def describe(self) -> str:
        return "writes what the test tells it"

    async def write(self, ctx: CoderContext) -> CoderResult:
        self.seen.append(ctx)
        if self.gate is not None:
            await self.gate.wait()
        step = self.rounds[min(ctx.round, len(self.rounds)) - 1]
        if isinstance(step, Exception):
            raise step
        for rel, text in step.items():
            p = ctx.dir / rel
            if rel.startswith("!"):  # a path no coder may write: put it there the way an agent would
                p = ctx.dir / rel[1:]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
            else:
                write_file(ctx.dir, rel, text)
        return CoderResult(note=f"round {ctx.round}", calls=1, cost_usd=0.01, model="fake-model")


def failing(message: str) -> CoderError:
    return CoderError(message, calls=2, cost_usd=0.02)


def run_pytest(d: Path) -> dict:
    """What rpc.sys.verify answers, from a real pytest run on the folder (the sealed container is Docker's job)."""
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=d,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (p.stdout + p.stderr)[-4000:]
    return {"name": d.name, "passed": p.returncode == 0, "stage": "tests", "exit_code": p.returncode, "output": out}


class FakeSupervisor:
    """rpc.sys.list / verify / deploy / snapshot / remove on an InMemoryBus. `verify` defaults to pytest on the staged
    folder."""

    def __init__(
        self,
        bus: InMemoryBus,
        grown: Path,
        modules: list[str] | None = None,
        verify: Callable[[Path], dict] | None = None,
        deploy_error: str | None = None,
        answer: set[str] | None = None,
    ) -> None:
        self.bus = bus
        self.grown = grown
        self.modules = modules or ["hello"]
        self.verify_fn = verify or run_pytest
        self.deploy_error = deploy_error
        self.answer = answer if answer is not None else {"list", "verify", "deploy", "snapshot", "remove"}
        self.verified: list[str] = []
        self.deployed: list[str] = []
        self.snapshots: list[tuple[str, str]] = []  # (name, label), in order
        self.snapshot_error: str | None = None
        self.events: list[str] = []  # snapshot:<name>, deploy:<name>: what happened in which order
        self.folders: list[str] = []
        self.list_error: str | None = None
        self.removed: list[tuple[str, str]] = []  # (name, label), in order
        self.remove_error: str | None = None
        self.remove_gate: asyncio.Event | None = None  # set it to hold a removal until the test lets it go
        self.dropped: set[str] = set()  # modules whose data a removal copied and dropped: a second one has none

    async def start(self) -> None:
        for action in self.answer:
            await self.bus.subscribe(f"rpc.sys.{action}", getattr(self, f"_{action}"))

    async def _list(self, msg) -> None:
        if self.list_error:
            await msg.respond({"ok": False, "error": self.list_error})
            return
        modules = [{"name": n, "status": "running"} for n in self.modules]
        grown = (
            sorted(d.name for d in self.grown.iterdir() if d.is_dir() and not d.name.startswith("."))
            if (self.grown.is_dir())
            else []
        )
        await msg.respond({"ok": True, "modules": modules, "folders": self.folders, "grown": grown})

    async def _snapshot(self, msg) -> None:
        name, label = msg.data["name"], msg.data["label"]
        if self.snapshot_error:
            await msg.respond({"ok": False, "error": self.snapshot_error})
            return
        self.snapshots.append((name, label))
        self.events.append(f"snapshot:{name}")
        await msg.respond({"ok": True, "name": name, "volume": f"test-data-{name}-{label}"})

    async def _remove(self, msg) -> None:
        name, label = msg.data["name"], msg.data["label"]
        if self.remove_gate is not None:
            await self.remove_gate.wait()
        if self.remove_error:
            await msg.respond({"ok": False, "error": self.remove_error})
            return
        self.removed.append((name, label))
        self.events.append(f"remove:{name}")
        listed = name in self.modules
        if listed:
            self.modules.remove(name)
        data = None if name in self.dropped else f"test-data-{name}-{label}"
        self.dropped.add(name)
        reply = {"name": name, "stopped": listed, "data": data, "listed": listed}
        await msg.respond({"ok": True, **reply})

    async def _verify(self, msg) -> None:
        name = msg.data["name"]
        assert msg.data.get("staging") is True
        self.verified.append(name)
        result = await asyncio.to_thread(self.verify_fn, self.grown / ".staging" / name)
        await msg.respond({"ok": True, "seconds": 0.1, "timed_out": False, **result})

    async def _deploy(self, msg) -> None:
        name = msg.data["name"]
        if self.deploy_error:
            await msg.respond({"ok": False, "error": self.deploy_error})
            return
        manifest = self.grown / name / "manifest.yaml"
        assert manifest.exists(), "deploy before promote"
        version = next(
            line.split(":", 1)[1].strip() for line in manifest.read_text().splitlines() if line.startswith("version:")
        )
        self.deployed.append(name)
        self.events.append(f"deploy:{name}")
        await msg.respond({"ok": True, "name": name, "image": f"test/mod-{name}:{version}", "status": "running"})


def make_pipeline(bus: InMemoryBus, grown: Path, max_rounds: int = 3) -> Pipeline:
    return Pipeline(
        bus,
        Workspace(grown, TEMPLATE),
        GrownRepo(grown),
        brief(),
        max_rounds=max_rounds,
        verify_timeout=60,
        deploy_timeout=10,
    )


def git(grown: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=grown, capture_output=True, text=True, check=True).stdout
