"""One build end to end with a scripted coder: rounds, feedback, promote, a real git commit, deploy; and the
service around it: what it refuses, the queue, the events, the records, a restart."""

import asyncio

import pytest

from builder.coders import CoderUnavailable
from builder.pipeline import PipelineError
from builder.schemas import BuildRecord
from builder.service import BuilderService
from builder.workspace import Workspace
from mycelium_sdk import InMemoryBus, InMemoryKV, kv_key
from tests.unit.builder_fakes import (
    BROKEN,
    GOOD,
    SPEC,
    TEMPLATE,
    FakeCoder,
    FakeSupervisor,
    failing,
    git,
    make_pipeline,
)


async def run_pipeline(tmp_path, coder, max_rounds=3, **sup):
    bus = InMemoryBus()
    grown = tmp_path / "grown"
    supervisor = FakeSupervisor(bus, grown, **sup)
    await supervisor.start()
    record = BuildRecord(name="notes", spec=SPEC, coder="fake")
    rounds = []

    async def on_round(rec, rnd):
        rounds.append(rnd.model_copy())

    error = None
    try:
        await make_pipeline(bus, grown, max_rounds).run(record, coder, on_round)
    except PipelineError as e:
        error = e
    return record, rounds, error, supervisor, grown


# ---- the pipeline -------------------------------------------------------------------------------------


async def test_a_module_that_passes_is_promoted_committed_and_deployed(tmp_path):
    record, rounds, error, sup, grown = await run_pipeline(tmp_path, FakeCoder([GOOD]))

    assert error is None, error.output if error else ""
    assert [(r.n, r.stage, r.passed) for r in rounds] == [(1, "tests", True)]
    assert "6 passed" in rounds[0].output  # the coder's one, the template's two, the builder's three contract tests
    assert sup.verified == ["notes"] and sup.deployed == ["notes"]
    module = grown / "notes"
    assert (module / "SPEC.md").read_text() == SPEC and (module / "tests" / "test_contract.py").exists()
    assert "network: false" in (module / "manifest.yaml").read_text()  # the coder asked for the network
    assert not (grown / ".staging" / "notes").exists()
    assert git(grown, "log", "-1", "--format=%s").strip() == "notes v0.1.0"
    assert "coder fake (fake-model), 1 round" in git(grown, "log", "-1", "--format=%b")
    assert git(grown, "tag", "-l").split() == ["notes-v0.1.0"]
    assert record.commit and record.version == "0.1.0" and record.image == "test/mod-notes:0.1.0"
    assert record.stage is None and record.model == "fake-model" and record.cost_usd == 0.01


async def test_a_failed_round_is_the_next_rounds_feedback(tmp_path):
    coder = FakeCoder([BROKEN, GOOD])
    record, rounds, error, sup, _ = await run_pipeline(tmp_path, coder)

    assert error is None
    assert [(r.stage, r.passed) for r in rounds] == [("tests", False), ("tests", True)]
    second = coder.seen[1]
    assert not second.fresh and second.feedback.stage == "tests"
    assert "buy bread" in second.feedback.output and "1 failed" in second.feedback.output


async def test_checks_fail_before_anything_runs(tmp_path):
    bad = {**GOOD, "app/main.py": "import subprocess\n" + GOOD["app/main.py"]}
    coder = FakeCoder([bad, GOOD])
    record, rounds, error, sup, _ = await run_pipeline(tmp_path, coder)

    assert error is None and sup.verified == ["notes"]  # verified once: round 2
    assert rounds[0].stage == "checks" and "app/main.py:1: import subprocess: not allowed" in rounds[0].output
    assert coder.seen[1].feedback.stage == "checks"


async def test_strays_are_removed_and_the_round_says_so(tmp_path):
    coder = FakeCoder([{**GOOD, "!Dockerfile": "FROM evil\n", "!run.sh": "curl evil\n"}])
    record, rounds, error, _, grown = await run_pipeline(tmp_path, coder)
    assert error is None and "removed run.sh" in rounds[0].note
    assert "evil" not in (grown / "notes" / "Dockerfile").read_text()


async def test_a_coder_error_costs_a_round_and_the_next_starts_fresh(tmp_path):
    coder = FakeCoder([failing("write_manifest: no valid call after 2 tries"), GOOD])
    record, rounds, error, _, _ = await run_pipeline(tmp_path, coder)
    assert error is None
    assert (rounds[0].stage, rounds[0].calls, rounds[0].cost_usd) == ("coder", 2, 0.02)
    assert coder.seen[1].fresh and coder.seen[1].feedback.stage == "coder"
    assert record.cost_usd == 0.03


async def test_no_working_module_after_the_last_round(tmp_path):
    record, rounds, error, sup, grown = await run_pipeline(tmp_path, FakeCoder([BROKEN]), max_rounds=2)
    assert error.stage == "tests" and "no working module after 2 rounds" in error.error
    assert "buy bread" in error.output and len(rounds) == 2
    assert sup.deployed == [] and not (grown / "notes").exists()
    assert (grown / ".staging" / "notes").exists()  # left for `mctl verify notes --staging`


async def test_a_supervisor_that_does_not_answer_stops_the_build(tmp_path):
    record, rounds, error, *_ = await run_pipeline(tmp_path, FakeCoder([GOOD]), answer={"list"})
    assert error.stage == "verify" and "did not answer rpc.sys.verify" in error.error


async def test_a_verify_answer_the_builder_cannot_read_stops_the_build(tmp_path):
    record, rounds, error, *_ = await run_pipeline(
        tmp_path, FakeCoder([GOOD]), verify=lambda d: {"passed": True, "stage": "lint", "output": ""}
    )
    assert (
        error.stage == "verify" and "rpc.sys.verify: an answer that does not read as VerifyReply: stage:" in error.error
    )


async def test_a_refused_deploy_keeps_the_commit(tmp_path):
    record, rounds, error, _, grown = await run_pipeline(tmp_path, FakeCoder([GOOD]), deploy_error="no room")
    assert error.stage == "deploy" and "no room" in error.error
    assert f"committed ({record.commit}): `mctl deploy notes`" in error.error
    assert record.commit and (grown / "notes").exists()


async def test_a_commit_that_fails_puts_the_module_back_in_staging(tmp_path, monkeypatch):
    from builder.repo import GrownRepo

    async def broken(self, name, version, message):
        raise RuntimeError("git commit: disk full")

    monkeypatch.setattr(GrownRepo, "commit", broken)
    record, rounds, error, sup, grown = await run_pipeline(tmp_path, FakeCoder([GOOD]))
    assert error.stage == "promote" and "could not commit it: git commit: disk full" in error.error
    assert not (grown / "notes").exists() and (grown / ".staging" / "notes" / "app" / "main.py").exists()
    assert sup.deployed == []


# ---- the service --------------------------------------------------------------------------------------


async def service(tmp_path, coder=None, modules=None, verify=None, **kw):
    bus = InMemoryBus()
    kv = InMemoryKV()
    grown = tmp_path / "grown"
    sup = FakeSupervisor(bus, grown, modules=modules, verify=verify)
    await sup.start()
    coder = coder or FakeCoder([GOOD])
    svc = BuilderService(bus, kv, make_pipeline(bus, grown), Workspace(grown, TEMPLATE), {"fake": coder}, "fake", **kw)
    await svc.start()
    return svc, bus, kv, coder, grown


async def until(predicate, timeout=60.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.02)


def passes(_d):
    return {"passed": True, "stage": "tests", "exit_code": 0, "output": "1 passed"}


async def test_a_build_runs_and_says_so(tmp_path):
    svc, bus, kv, coder, grown = await service(tmp_path)
    reply = await bus.request(
        "rpc.build.start", {"name": "notes", "spec": SPEC, "cause": "m1", "hops": 1, "thread": "t"}
    )
    assert reply["ok"] and reply["position"] == 0
    await until(lambda: bus.events("build.done") or bus.events("build.failed"))
    await svc.stop()

    assert [s for s, _ in bus.events("build.>")] == ["build.started", "build.progress", "build.done"]
    done = bus.events("build.done")[0][1]
    assert done["build_id"] == reply["build_id"] and done["cause"] == "m1" and done["hops"] == 2
    assert done["thread"] == "t" and done["version"] == "0.1.0" and done["commit"]
    record = await bus.request("rpc.build.get", {"build_id": reply["build_id"]})
    assert record["status"] == "done" and record["rounds"][0]["passed"] and record["finished"]
    listed = await bus.request("rpc.build.list", {})
    assert [b["name"] for b in listed["builds"]] == ["notes"] and listed["builds"][0]["rounds"] == 1
    assert "spec" not in listed["builds"][0]


async def test_get_and_list_read_their_requests(tmp_path):
    svc, bus, *_ = await service(tmp_path)
    missing = await bus.request("rpc.build.get", {})
    unknown = await bus.request("rpc.build.get", {"build_id": "nope"})
    bad_limit = await bus.request("rpc.build.list", {"limit": "ten"})
    empty = await bus.request("rpc.build.list", {"limit": 500})
    coders = await bus.request("rpc.build.coders", {})
    await svc.stop()
    assert missing == {"ok": False, "error": "build_id: Field required"}
    assert unknown == {"ok": False, "error": "no build 'nope'"}
    assert bad_limit["ok"] is False and bad_limit["error"].startswith("limit: ")
    assert empty == {"ok": True, "builds": []}  # a limit past 100 is kept to 100, not refused
    assert coders == {"ok": True, "default": "fake", "coders": [{"name": "fake", "ready": True, "reason": None}]}


@pytest.mark.parametrize(
    "payload, error",
    [
        ({"name": "Bad", "spec": SPEC}, "lowercase slug"),
        ({"name": "memory", "spec": SPEC}, "reserved"),
        ({"name": "notes", "spec": "short"}, "spec"),
        ({"name": "notes", "spec": SPEC, "coder": "nobody"}, "no coder 'nobody'; one of fake"),
        ({"name": "hello", "spec": SPEC}, "a module named 'hello' already exists"),
    ],
)
async def test_start_refuses(tmp_path, payload, error):
    svc, bus, *_ = await service(tmp_path)
    reply = await bus.request("rpc.build.start", payload)
    await svc.stop()
    assert reply["ok"] is False and error in reply["error"], reply


async def test_start_refuses_a_grown_name_a_busy_name_and_a_full_queue(tmp_path):
    coder = FakeCoder([GOOD])
    coder.gate = asyncio.Event()
    svc, bus, kv, _, grown = await service(tmp_path, coder=coder, verify=passes, max_queue=1)
    (grown / "done-one").mkdir(parents=True)

    first = await bus.request("rpc.build.start", {"name": "notes", "spec": SPEC})
    await until(lambda: coder.seen)  # running, held at the gate
    second = await bus.request("rpc.build.start", {"name": "other", "spec": SPEC})
    again = await bus.request("rpc.build.start", {"name": "notes", "spec": SPEC})
    full = await bus.request("rpc.build.start", {"name": "third", "spec": SPEC})
    grown_one = await bus.request("rpc.build.start", {"name": "done-one", "spec": SPEC})
    coder.gate.set()
    await until(lambda: len(bus.events("build.done")) == 2)
    await svc.stop()

    assert first["position"] == 0 and second["position"] == 1
    assert "'notes' is already being built" in again["error"]
    assert "busy: 1 builds are waiting" in full["error"]
    assert "'done-one' has already been grown" in grown_one["error"]


async def test_start_refuses_when_the_coder_cannot_work_or_the_supervisor_is_down(tmp_path):
    svc, bus, *_ = await service(tmp_path, coder=FakeCoder([GOOD], reason="the gateway is not answering"))
    reply = await bus.request("rpc.build.start", {"name": "notes", "spec": SPEC})
    assert "the fake coder cannot build now: the gateway is not answering" in reply["error"]
    coders = await bus.request("rpc.build.coders", {})
    assert coders["default"] == "fake" and coders["coders"] == [
        {"name": "fake", "ready": False, "reason": "the gateway is not answering"}
    ]
    await svc.stop()

    bus = InMemoryBus()
    svc = BuilderService(
        bus,
        InMemoryKV(),
        make_pipeline(bus, tmp_path),
        Workspace(tmp_path, TEMPLATE),
        {"fake": FakeCoder([GOOD])},
        "fake",
    )
    await svc.start()
    reply = await bus.request("rpc.build.start", {"name": "notes", "spec": SPEC})
    await svc.stop()
    assert "the supervisor is not answering" in reply["error"]


async def test_an_unavailable_coder_fails_the_build_at_the_coder(tmp_path):
    svc, bus, *_ = await service(tmp_path, coder=FakeCoder([CoderUnavailable("the 'coder' model is not answering")]))
    reply = await bus.request("rpc.build.start", {"name": "notes", "spec": SPEC})
    await until(lambda: bus.events("build.failed"))
    await svc.stop()
    failed = bus.events("build.failed")[0][1]
    assert failed["build_id"] == reply["build_id"] and failed["stage"] == "coder"
    assert "not answering" in failed["error"] and failed["rounds"] == 1  # the round it stopped in is kept


async def test_a_build_that_takes_too_long_fails_where_it_was(tmp_path):
    coder = FakeCoder([GOOD])
    coder.gate = asyncio.Event()  # never set
    svc, bus, *_ = await service(tmp_path, coder=coder, build_timeout=0.2)
    await bus.request("rpc.build.start", {"name": "notes", "spec": SPEC})
    await until(lambda: bus.events("build.failed"))
    await svc.stop()
    failed = bus.events("build.failed")[0][1]
    assert failed["stage"] == "coder" and "longer than 0.2s" in failed["error"]


def test_the_default_coder_must_exist(tmp_path):
    bus = InMemoryBus()
    with pytest.raises(ValueError, match="BUILDER_CODER='claude_code'"):
        BuilderService(bus, InMemoryKV(), None, Workspace(tmp_path, TEMPLATE), {"fake": FakeCoder([])}, "claude_code")


async def test_a_restart_fails_the_running_build_and_runs_the_waiting_one(tmp_path):
    bus = InMemoryBus()
    kv = InMemoryKV()
    grown = tmp_path / "grown"
    sup = FakeSupervisor(bus, grown, verify=passes)
    await sup.start()
    running = BuildRecord(id="0000000000001aaaaaaaa", name="half", spec=SPEC, coder="fake", status="building")
    waiting = BuildRecord(id="0000000000002bbbbbbbb", name="notes", spec=SPEC, coder="fake")
    for r in (running, waiting):
        await kv.put(kv_key("builds", r.id), r.model_dump())

    svc = BuilderService(
        bus, kv, make_pipeline(bus, grown), Workspace(grown, TEMPLATE), {"fake": FakeCoder([GOOD])}, "fake"
    )
    await svc.start()
    await until(lambda: bus.events("build.done"))
    await svc.stop()

    failed = bus.events("build.failed")[0][1]
    assert failed["build_id"] == running.id and failed["stage"] == "restart"
    assert bus.events("build.done")[0][1]["build_id"] == waiting.id
    assert (await kv.get(kv_key("builds", running.id)))["status"] == "failed"


class FlakyKV(InMemoryKV):
    """Fails the first time a build is saved as building: the KV blinked."""

    def __init__(self):
        super().__init__()
        self.failed = False

    async def put(self, key, value):
        if value.get("status") == "building" and not self.failed:
            self.failed = True
            raise TimeoutError("nats: timeout")
        await super().put(key, value)


async def test_the_worker_outlives_a_kv_that_fails(tmp_path):
    bus = InMemoryBus()
    grown = tmp_path / "grown"
    await FakeSupervisor(bus, grown, verify=passes).start()
    svc = BuilderService(
        bus, FlakyKV(), make_pipeline(bus, grown), Workspace(grown, TEMPLATE), {"fake": FakeCoder([GOOD])}, "fake"
    )
    await svc.start()
    first = await bus.request("rpc.build.start", {"name": "notes", "spec": SPEC})
    await until(lambda: bus.events("build.failed"))
    second = await bus.request("rpc.build.start", {"name": "notes", "spec": SPEC})  # the name is free again
    await until(lambda: bus.events("build.done"))
    await svc.stop()
    failed = bus.events("build.failed")[0][1]
    assert failed["build_id"] == first["build_id"] and "internal: TimeoutError" in failed["error"]
    assert bus.events("build.done")[0][1]["build_id"] == second["build_id"]


async def test_a_name_with_a_folder_is_taken_and_a_failed_list_refuses(tmp_path):
    svc, bus, *_ = await service(tmp_path)
    await svc.stop()
    sup = FakeSupervisor(InMemoryBus(), tmp_path, modules=[])
    svc.bus = sup.bus
    sup.folders = ["drafts"]
    await sup.start()
    with pytest.raises(ValueError, match="a module named 'drafts' already exists"):
        await svc.start_build({"name": "drafts", "spec": SPEC})
    sup.list_error = "registry down"
    with pytest.raises(ValueError, match="could not list modules: registry down"):
        await svc.start_build({"name": "notes", "spec": SPEC})


async def test_an_unwritable_grown_dir_is_refused_with_how_to_fix_it(tmp_path):
    (tmp_path / "grown").write_text("not a folder")
    svc, bus, *_ = await service(tmp_path)
    reply = await bus.request("rpc.build.start", {"name": "notes", "spec": SPEC})
    await svc.stop()
    assert "GROWN_DIR is not writable" in reply["error"] and "mkdir -p grown" in reply["error"]


async def test_recover_skips_a_record_it_cannot_read(tmp_path):
    bus = InMemoryBus()
    kv = InMemoryKV()
    await kv.put(kv_key("builds", "0000000000001aaaaaaaa"), {"id": "x", "status": "sideways"})
    grown = tmp_path / "grown"
    svc = BuilderService(
        bus, kv, make_pipeline(bus, grown), Workspace(grown, TEMPLATE), {"fake": FakeCoder([GOOD])}, "fake"
    )
    await svc.start()
    listed = await bus.request("rpc.build.list", {})
    await svc.stop()
    assert listed == {"ok": True, "builds": []}


async def test_a_coder_error_round_keeps_the_failure_still_to_fix(tmp_path):
    coder = FakeCoder([BROKEN, failing("write_files: no valid call after 2 tries"), GOOD])
    record, rounds, error, *_ = await run_pipeline(tmp_path, coder)
    assert error is None and [r.stage for r in rounds] == ["tests", "coder", "tests"]
    third = coder.seen[2].feedback
    assert third.stage == "tests" and "buy bread" in third.output and "could not write its fix" in third.output
    assert not coder.seen[2].fresh


async def test_a_spec_of_blanks_is_refused(tmp_path):
    svc, bus, *_ = await service(tmp_path)
    reply = await bus.request("rpc.build.start", {"name": "notes", "spec": " " * 40})
    await svc.stop()
    assert reply["ok"] is False and "at least 20 characters" in reply["error"]


async def test_a_retired_name_can_grow_again(tmp_path):
    svc, bus, *_ = await service(tmp_path)
    await svc.stop()
    svc.bus = InMemoryBus()

    async def listing(msg):
        modules = [{"name": "notes", "status": "retired"}, {"name": "hello", "status": "stopped"}]
        await msg.respond({"ok": True, "modules": modules, "folders": []})

    await svc.bus.subscribe("rpc.sys.list", listing)
    assert await svc._known_modules() == {"hello"}


async def test_growing_a_name_again_moves_its_tag_and_a_failed_tag_keeps_the_commit(tmp_path, monkeypatch):
    from builder.repo import GrownRepo

    repo = GrownRepo(tmp_path)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.txt").write_text("one")
    first = await repo.commit("notes", "0.1.0", "notes v0.1.0")
    (tmp_path / "notes" / "a.txt").write_text("two")
    second = await repo.commit("notes", "0.1.0", "notes v0.1.0 again")
    assert git(tmp_path, "rev-parse", "--short=12", "notes-v0.1.0^{commit}").strip() == second != first

    original = GrownRepo._git

    async def no_tags(self, *args):
        if args[0] == "tag":
            raise RuntimeError("git tag: locked")
        return await original(self, *args)

    monkeypatch.setattr(GrownRepo, "_git", no_tags)
    (tmp_path / "notes" / "a.txt").write_text("three")
    third = await repo.commit("notes", "0.1.0", "notes once more")
    assert third == git(tmp_path, "rev-parse", "--short=12", "HEAD").strip()  # committed, though untagged
