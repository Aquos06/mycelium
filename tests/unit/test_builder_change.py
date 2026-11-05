"""A change build: a module the builder grew, edited as it is. It starts from a copy of the module, the coder
gets the change, the version goes up, the old version stays tagged, the data is copied before the new version
deploys, and a change that fails leaves the module as it was."""

import asyncio

import pytest

from builder.coders import MyceliumCoder
from builder.pipeline import change_spec, next_version
from builder.prompts.agent import agent_prompt
from builder.schemas import CoderContext, CoderResult, Feedback
from builder.service import BuilderService
from builder.workspace import Workspace
from mycelium_sdk import InMemoryBus, InMemoryKV
from tests.unit.builder_fakes import (
    BROKEN,
    CODE,
    GOOD,
    MANIFEST,
    SPEC,
    TEMPLATE,
    FakeCoder,
    FakeSupervisor,
    brief,
    git,
    make_pipeline,
)
from tests.unit.test_builder_coder import ScriptedGateway, tool

CHANGE = "Why: he wants to know how many notes he kept.\n\n- also answer `count`: how many notes were kept"

COUNTED = {
    "manifest.yaml": MANIFEST.replace(
        "    returns: {note: string}\n",
        "    returns: {note: string}\n  count:\n    description: How many notes were kept.\n"
        "    returns: {count: number}\n",
    ),
    "app/main.py": CODE.replace('state = {"last": ""}', 'state = {"last": "", "count": 0}')
    .replace(
        '            state["last"] = text[5:]\n',
        '            state["last"] = text[5:]\n            state["count"] += 1\n',
    )
    .replace(
        "    return mod\n",
        '    @mod.on_request("count")\n    async def count(data):\n        return {"count": state["count"]}\n\n'
        "    return mod\n",
    ),
    "tests/test_notes.py": GOOD["tests/test_notes.py"],
}


class Recorder(FakeCoder):
    """A FakeCoder that also keeps what the folder held when each round began."""

    def __init__(self, rounds) -> None:
        super().__init__(rounds)
        self.found: list[dict[str, str]] = []

    async def write(self, ctx: CoderContext) -> CoderResult:
        self.found.append({p.relative_to(ctx.dir).as_posix(): p.read_text() for p in ctx.dir.rglob("*") if p.is_file()})
        return await super().write(ctx)


async def grown_notes(tmp_path, changer):
    """A builder with `notes` 0.1.0 already grown, built and deployed; `changer` writes the change builds."""
    bus = InMemoryBus()
    grown = tmp_path / "grown"
    sup = FakeSupervisor(bus, grown)
    await sup.start()
    coders = {"fake": FakeCoder([GOOD]), "changer": changer}
    svc = BuilderService(bus, InMemoryKV(), make_pipeline(bus, grown), Workspace(grown, TEMPLATE), coders, "fake")
    await svc.start()
    first = await finished(svc, await svc.start_build({"name": "notes", "spec": SPEC}))
    assert first.status == "done", first.error
    return svc, bus, sup, grown


async def finished(svc, reply, timeout=60.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while True:
        record = await svc.get({"build_id": reply.build_id})
        if record.status in ("done", "failed"):
            return record
        if loop.time() > end:
            raise AssertionError("timed out waiting for the build")
        await asyncio.sleep(0.02)


def files(d) -> dict[str, str]:
    return {p.relative_to(d).as_posix(): p.read_text() for p in sorted(d.rglob("*")) if p.is_file()}


async def change(svc, text=CHANGE, coder="changer"):
    return await finished(svc, await svc.start_build({"name": "notes", "change": text, "coder": coder}))


# ---- a change that works -----------------------------------------------------------------------------


async def test_a_change_edits_the_module_as_it_is_and_keeps_the_old_version_tagged(tmp_path):
    changer = Recorder([COUNTED])
    svc, bus, sup, grown = await grown_notes(tmp_path, changer)
    first_commit = git(grown, "rev-parse", "--short=12", "HEAD").strip()
    done = []
    await bus.subscribe("build.done", lambda m: done.append(m.data))

    record = await change(svc)

    assert record.status == "done", f"{record.error}\n{record.output}"
    assert (record.mode, record.base_version, record.version) == ("change", "0.1.0", "0.2.0")
    assert record.base_commit == first_commit and record.snapshot == f"test-data-notes-v0.1.0-{record.id}"
    ctx = changer.seen[0]
    assert ctx.change == CHANGE and not ctx.fresh and ctx.feedback is None
    assert changer.found[0]["app/main.py"] == CODE  # the coder started from the module as it runs
    assert ctx.spec == f"{SPEC.strip()}\n\n## Change in v0.2.0\n\n{CHANGE}\n"

    module = grown / "notes"
    assert (
        "count:" in (module / "manifest.yaml").read_text()
        and "version: 0.2.0" in (module / "manifest.yaml").read_text()
    )
    assert (module / "SPEC.md").read_text().endswith(f"## Change in v0.2.0\n\n{CHANGE}\n")
    assert git(grown, "tag", "-l").split() == ["notes-v0.1.0", "notes-v0.2.0"]
    assert "count" not in git(grown, "show", "notes-v0.1.0:notes/app/main.py")  # the way back
    assert git(grown, "log", "-1", "--format=%s").strip() == "notes v0.2.0"
    body = git(grown, "log", "-1", "--format=%b")
    assert "change from v0.1.0: Why: he wants" in body and f"data copied to {record.snapshot} first" in body
    assert sup.events == ["deploy:notes", "snapshot:notes", "deploy:notes"]  # the copy before the new version runs
    assert record.image == "test/mod-notes:0.2.0"
    assert not (grown / ".staging" / "notes").exists() and not (grown / ".staging" / "notes.previous").exists()
    assert done[-1]["mode"] == "change" and done[-1]["version"] == "0.2.0"


async def test_each_change_bumps_the_version_and_adds_its_section_to_the_spec(tmp_path):
    svc, _, _, grown = await grown_notes(tmp_path, FakeCoder([COUNTED]))
    assert (await change(svc)).version == "0.2.0"
    second = await change(svc, "Why: shorter answers.\n\n- `last` gives back the note without trailing spaces")
    assert second.status == "done" and (second.base_version, second.version) == ("0.2.0", "0.3.0")
    spec = (grown / "notes" / "SPEC.md").read_text()
    assert spec.index("## Change in v0.2.0") < spec.index("## Change in v0.3.0")
    assert git(grown, "tag", "-l").split() == ["notes-v0.1.0", "notes-v0.2.0", "notes-v0.3.0"]


# ---- a change that does not work changes nothing ------------------------------------------------------


async def test_a_change_that_fails_its_tests_leaves_the_module_as_it_was(tmp_path):
    svc, _, sup, grown = await grown_notes(tmp_path, FakeCoder([BROKEN]))
    before, head = files(grown / "notes"), git(grown, "rev-parse", "HEAD")

    record = await change(svc)

    assert record.status == "failed" and record.stage == "tests"
    assert files(grown / "notes") == before and git(grown, "rev-parse", "HEAD") == head
    assert sup.snapshots == [] and sup.deployed == ["notes"]  # deployed once: the first build
    assert (grown / ".staging" / "notes").exists()  # left for `mctl verify notes --staging`


async def test_no_copy_of_the_data_no_change(tmp_path):
    svc, _, sup, grown = await grown_notes(tmp_path, FakeCoder([COUNTED]))
    sup.snapshot_error = "docker: no space left on device"
    before = files(grown / "notes")

    record = await change(svc)

    assert record.status == "failed" and record.stage == "snapshot"
    assert "no space left" in record.error and "Nothing was changed: notes still runs as v0.1.0" in record.error
    assert files(grown / "notes") == before and git(grown, "tag", "-l").split() == ["notes-v0.1.0"]
    assert sup.deployed == ["notes"]


async def test_a_change_that_fails_to_deploy_says_where_the_old_version_and_its_data_are(tmp_path):
    svc, _, sup, grown = await grown_notes(tmp_path, FakeCoder([COUNTED]))
    sup.deploy_error = "docker: port in use"

    record = await change(svc)

    assert record.status == "failed" and record.stage == "deploy"
    assert "`mctl deploy notes`" in record.error
    assert f"v0.1.0 is tagged notes-v0.1.0 and its data is in test-data-notes-v0.1.0-{record.id}" in record.error


# ---- what a change build refuses ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_, error",
    [
        ({"name": "hello", "change": CHANGE}, "there is no grown module 'hello' to change (it is hand-written"),
        ({"name": "ghost", "change": CHANGE}, "there is no grown module 'ghost' to change: the builder changes only"),
        ({"name": "notes", "spec": SPEC}, "to change it, send a `change` instead of a spec"),
        ({"name": "notes", "spec": SPEC, "change": CHANGE}, "a spec (a new module) or a change"),
        ({"name": "notes", "change": "count notes"}, "a change says what the module should do now: at least 20"),
    ],
)
async def test_what_a_change_build_refuses(tmp_path, request_, error):
    svc, bus, *_ = await grown_notes(tmp_path, FakeCoder([COUNTED]))
    reply = await bus.request("rpc.build.start", request_)
    assert reply["ok"] is False and error in reply["error"], reply["error"]


# ---- the parts ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("base, after", [("0.1.0", "0.2.0"), ("1.4.2", "1.5.0"), ("draft", "0.2.0")])
def test_next_version(base, after):
    assert next_version(base) == after


def test_a_module_without_a_spec_still_gets_its_change_as_the_last_section():
    assert change_spec("", "- count notes", "0.2.0").startswith("(no SPEC.md was kept for this module")
    assert change_spec("# Spec: notes\n", "- count notes", "0.2.0").endswith("## Change in v0.2.0\n\n- count notes\n")


def test_promote_swaps_the_module_and_demote_puts_the_old_one_back(tmp_path):
    ws = Workspace(tmp_path, TEMPLATE)
    old = ws.start("notes", SPEC)
    (old / "app" / "main.py").write_text("old\n")
    ws.promote("notes")
    new = ws.start_change("notes", SPEC + "\n## Change in v0.2.0\n\n- more\n")
    assert (new / "app" / "main.py").read_text() == "old\n"  # a copy of the module as it is
    (new / "app" / "main.py").write_text("new\n")

    ws.promote("notes", replace=True)
    assert (ws.module("notes") / "app" / "main.py").read_text() == "new\n"
    ws.demote("notes")  # the commit failed
    assert (ws.module("notes") / "app" / "main.py").read_text() == "old\n"
    assert (ws.staging("notes") / "app" / "main.py").read_text() == "new\n"

    ws.promote("notes", replace=True)
    ws.settle("notes")  # committed: the old version lives in git
    assert not ws.previous("notes").exists()
    with pytest.raises(FileExistsError):
        ws.start_change("notes", SPEC) and ws.promote("notes")  # a new module never replaces one


# ---- what the coders are told -------------------------------------------------------------------------


def change_ctx(d, feedback=None) -> CoderContext:
    spec = change_spec(SPEC, CHANGE, "0.2.0")
    return CoderContext(
        build_id="b1", name="notes", spec=spec, dir=d, round=1 if feedback is None else 2, fresh=False,
        change=CHANGE, feedback=feedback, brief=brief(),
    )  # fmt: skip


@pytest.fixture
def running(tmp_path):
    ws = Workspace(tmp_path, TEMPLATE)
    d = ws.start("notes", SPEC)
    for rel, text in GOOD.items():
        (d / rel).write_text(text)
    ws.promote("notes")
    return ws.start_change("notes", change_spec(SPEC, CHANGE, "0.2.0"))


async def test_our_coder_changes_the_files_it_is_shown_in_one_call(running):
    bus = InMemoryBus()
    gw = ScriptedGateway(
        bus,
        [tool("write_files", {"files": [{"path": "app/main.py", "content": COUNTED["app/main.py"]}], "note": "count"})],
    )
    await gw.start()
    res = await MyceliumCoder(bus, backoff=(0, 0)).write(change_ctx(running))

    (request,) = gw.requests
    prompt = request["messages"][0]["content"]
    assert request["tool_choice"] == "write_files"
    assert "## The module to change: `notes`" in prompt and "the last section is the change this build makes" in prompt
    assert "## The files now: the module as it runs" in prompt and CODE.strip() in prompt
    assert f"## This build: the change\n\n{CHANGE}" in prompt
    assert "never drop, rename or recreate a table" in prompt and "the old entries still read" in prompt
    assert (running / "app" / "main.py").read_text() == COUNTED["app/main.py"] and res.note == "count"


async def test_a_failed_change_round_is_fixed_with_the_change_still_in_view(running):
    bus = InMemoryBus()
    gw = ScriptedGateway(bus, [tool("write_files", {"files": [{"path": "app/main.py", "content": CODE}]})])
    await gw.start()
    await MyceliumCoder(bus, backoff=(0, 0)).write(change_ctx(running, Feedback(stage="tests", output="1 failed")))
    prompt = gw.requests[0]["messages"][0]["content"]
    assert "Round 2: the last round failed at tests" in prompt
    assert f"keep that data readable. The change:\n\n{CHANGE}" in prompt


def test_an_agent_is_told_to_change_the_module_and_keep_its_data(running):
    user = agent_prompt(change_ctx(running)).user
    assert "You are in the module's folder: the module as it runs now" in user
    assert "SPEC.md (its last section is the\nchange to make)" in user
    assert "never drop, rename or recreate a table" in user and "the old entries still read" in user
