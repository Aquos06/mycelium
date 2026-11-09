"""Deleting a module the builder grew (rpc.build.remove): the supervisor copies its data and removes the rest, then its
folder leaves GROWN_DIR in one commit while a tag of its own keeps the code. A hand-written module, a module being built and
a name nobody has are refused; a deletion that failed halfway is finished by asking again."""

import asyncio
import re

import pytest

from builder.repo import GrownRepo
from builder.schemas import BuildRequest, RemoveRequest
from builder.service import BuilderService
from builder.workspace import Workspace
from mycelium_sdk import InMemoryBus, InMemoryKV
from tests.unit.builder_fakes import GOOD, SPEC, TEMPLATE, FakeCoder, FakeSupervisor, git, make_pipeline
from tests.unit.test_builder_change import finished, grown_notes

LABEL = re.compile(r"^v0\.1\.0-removed-\d{8}T\d{6}Z$")


async def remove(bus, name="notes") -> dict:
    return await bus.request("rpc.build.remove", {"name": name}, timeout=10)


async def test_a_grown_module_is_deleted_with_its_data_copied_and_its_code_kept_in_git(tmp_path):
    svc, bus, sup, grown = await grown_notes(tmp_path, FakeCoder([GOOD]))
    built = git(grown, "rev-parse", "notes-v0.1.0^{commit}")
    (grown / "notes" / "app" / "__pycache__").mkdir()  # what git does not track goes too
    (grown / ".staging" / "notes").mkdir(parents=True)  # and what a build left in staging

    reply = await remove(bus)

    assert reply["ok"] is True, reply
    ((name, label),) = sup.removed
    assert name == "notes" and LABEL.match(label)
    assert reply == {
        "ok": True,
        "name": "notes",
        "version": "0.1.0",
        "data": f"test-data-notes-{label}",
        "commit": git(grown, "rev-parse", "--short=12", "HEAD").strip(),
        "tag": f"notes-{label}",
    }
    assert sup.events[-1] == "remove:notes"  # the supervisor first: the folder goes only once the module is gone
    assert not (grown / "notes").exists() and not (grown / ".staging" / "notes").exists()
    assert git(grown, "log", "-1", "--format=%s").strip() == "remove notes v0.1.0"
    assert f"its data copied to test-data-notes-{label}" in git(grown, "log", "-1", "--format=%b")
    assert git(grown, "status", "--porcelain") == ""
    assert "def build" in git(grown, "show", f"notes-{label}:notes/app/main.py")  # the way back

    again = await svc.start_build(BuildRequest(name="notes", spec=SPEC))  # the name is free again
    assert (await finished(svc, again)).status == "done"
    assert git(grown, "rev-parse", "notes-v0.1.0^{commit}") != built  # the new notes took its version's tag
    assert git(grown, "rev-parse", f"notes-{label}^{{commit}}") == built  # its own still leads to the deleted one


async def test_a_module_listed_whose_folder_is_gone_is_removed_without_a_commit(tmp_path):
    svc, bus, sup, grown = await grown_notes(tmp_path, FakeCoder([GOOD]))
    sup.modules.append("ghost")
    head = git(grown, "rev-parse", "HEAD")
    reply = await remove(bus, "ghost")
    assert reply["ok"] is True and reply["commit"] is None and reply["tag"] is None
    assert sup.removed[-1][1].startswith("removed-")  # no version known
    assert git(grown, "rev-parse", "HEAD") == head


@pytest.mark.parametrize(
    ("name", "error"),
    [
        ("hello", "hello is hand-written (modules/hello): only a module the builder grew can be deleted here"),
        ("ghost", "there is no module 'ghost' to delete"),
        ("Bad Name", "must be a lowercase slug"),
    ],
)
async def test_what_a_deletion_refuses(tmp_path, name, error):
    svc, bus, sup, grown = await grown_notes(tmp_path, FakeCoder([GOOD]))
    sup.folders = ["hello", "notes"]
    reply = await remove(bus, name)
    assert reply["ok"] is False and error in reply["error"]
    assert not sup.removed and (grown / "notes").is_dir()


async def test_a_module_being_built_is_not_deleted(tmp_path):
    coder = FakeCoder([GOOD])
    svc, bus, sup, grown = await grown_notes(tmp_path, coder)
    coder.gate = asyncio.Event()  # the change build waits in the coder
    started = await svc.start_build(
        BuildRequest(name="notes", change="Why: more.\n\n- also count the notes", coder="fake")
    )
    reply = await remove(bus)
    assert reply["ok"] is False and f"'notes' is being built ({started.build_id})" in reply["error"]
    assert not sup.removed
    coder.gate.set()
    await finished(svc, started)


async def test_no_deletion_slips_in_while_a_build_of_it_is_being_started(tmp_path):
    svc, bus, sup, grown = await grown_notes(tmp_path, FakeCoder([GOOD]))
    gate = asyncio.Event()
    ensure = svc.pipeline.repo.ensure

    async def slow_ensure():  # one of the waits before the build is queued
        await gate.wait()
        await ensure()

    svc.pipeline.repo.ensure = slow_ensure
    starting = asyncio.create_task(
        svc.start_build(BuildRequest(name="notes", change="Why: more.\n\n- also count the notes", coder="fake"))
    )
    await asyncio.sleep(0.05)
    reply = await remove(bus)
    assert reply == {"ok": False, "error": "'notes' is being built; delete it once that build has ended"}
    assert not sup.removed
    gate.set()
    assert (await finished(svc, await starting)).status == "done"


async def test_no_build_of_a_module_starts_while_it_is_being_deleted(tmp_path):
    svc, bus, sup, grown = await grown_notes(tmp_path, FakeCoder([GOOD]))
    sup.remove_gate = asyncio.Event()
    deleting = asyncio.create_task(remove(bus))
    await asyncio.sleep(0.05)
    with pytest.raises(ValueError, match="being deleted right now"):
        await svc.start_build(BuildRequest(name="notes", change="Why: more.\n\n- also count the notes", coder="fake"))
    with pytest.raises(ValueError, match="already being deleted"):
        await svc.remove_module(RemoveRequest(name="notes"))
    sup.remove_gate.set()
    assert (await deleting)["ok"] is True


async def test_when_the_supervisor_will_not_remove_it_the_folder_stays(tmp_path):
    svc, bus, sup, grown = await grown_notes(tmp_path, FakeCoder([GOOD]))
    sup.remove_error = "internal: docker said no"
    head = git(grown, "rev-parse", "HEAD")
    reply = await remove(bus)
    assert reply == {"ok": False, "error": "the supervisor could not remove notes: internal: docker said no"}
    assert (grown / "notes").is_dir() and git(grown, "rev-parse", "HEAD") == head


async def test_a_commit_that_fails_puts_the_folder_back_and_asking_again_finishes(tmp_path):
    svc, bus, sup, grown = await grown_notes(tmp_path, FakeCoder([GOOD]))
    hook = grown / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    reply = await remove(bus)
    assert reply["ok"] is False
    assert reply["error"].startswith("notes is stopped and its data copied to test-data-notes-v0.1.0-removed-")
    assert "its folder could not leave GROWN_DIR" in reply["error"] and reply["error"].endswith("ask again to finish")
    assert (grown / "notes" / "manifest.yaml").is_file() and git(grown, "status", "--porcelain") == ""

    hook.unlink()
    again = await remove(bus)
    assert again["ok"] is True and again["commit"] and not (grown / "notes").exists()
    first, second = (label for _, label in sup.removed)
    assert again["data"] == f"test-data-notes-{first}"  # dropped by the first try, which kept where it went
    assert again["tag"] == f"notes-{second}"


async def test_the_supervisor_down_refuses_a_deletion(tmp_path):
    bus = InMemoryBus()
    grown = tmp_path / "grown"
    svc = BuilderService(
        bus, InMemoryKV(), make_pipeline(bus, grown), Workspace(grown, TEMPLATE), {"fake": FakeCoder([GOOD])}, "fake"
    )
    await svc.start()
    sup = FakeSupervisor(bus, grown, answer={"list"})  # lists, never removes
    await sup.start()
    (grown / "notes").mkdir(parents=True)
    svc.remove_timeout = 0.1
    reply = await remove(bus)
    assert reply["ok"] is False and "the supervisor did not answer within 0.1s" in reply["error"]
    assert (grown / "notes").is_dir()


async def test_the_repo_forgets_a_folder_it_never_committed(tmp_path):
    repo = GrownRepo(tmp_path / "grown")
    await repo.ensure()
    (tmp_path / "grown" / "stray" / "app").mkdir(parents=True)
    assert await repo.remove("stray", "remove stray", "stray-removed-1") is None
    assert not (tmp_path / "grown" / "stray").exists()
