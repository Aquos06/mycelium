"""A coding agent as the coder: what it is told, what the builder takes back from it, how it fails, and a whole
build where an agent writes the module."""

import pytest

from builder.coders import AgentCoder, CoderError, CoderUnavailable
from builder.schemas import BuildRecord, CoderContext, Feedback
from builder.workspace import CONTRACT, Workspace
from mycelium_sdk import InMemoryBus
from tests.unit.builder_fakes import GOOD, SPEC, TEMPLATE, FakeSupervisor, brief, make_pipeline


class AgentSupervisor(FakeSupervisor):
    """FakeSupervisor plus rpc.sys.agent / rpc.sys.agents: the agent leaves `left` (a dict, or a function of the
    folder it was given)."""

    def __init__(self, bus, grown, left=None, reply=None, agents=None, **kw):
        super().__init__(bus, grown, **kw)
        self.left = left if left is not None else GOOD
        self.reply = reply
        self.agents = agents if agents is not None else [{"name": "opencode", "ready": True, "reason": None}]
        self.answer |= {"agent", "agents"}
        self.requests: list[dict] = []
        self.exit_code = 0
        self.skipped: list[str] = []
        self.skipped_more = 0
        self.output = "....\n6 passed"

    async def _agent(self, msg) -> None:
        self.requests.append(msg.data)
        if self.reply is not None:
            await msg.respond(self.reply)
            return
        staged = self.grown / ".staging" / msg.data["name"]
        given = {p.relative_to(staged).as_posix(): p.read_text() for p in staged.rglob("*") if p.is_file()}
        left = self.left(given) if callable(self.left) else {**given, **self.left}
        await msg.respond(
            {
                "ok": True,
                "agent": msg.data["agent"],
                "name": msg.data["name"],
                "exit_code": self.exit_code,
                "timed_out": False,
                "output": self.output,
                "files": left,
                "skipped": self.skipped,
                "skipped_more": self.skipped_more,
                "seconds": 42.0,
            }
        )

    async def _agents(self, msg) -> None:
        await msg.respond({"ok": True, "agents": self.agents})


async def setup(tmp_path, **kw):
    bus = InMemoryBus()
    grown = tmp_path / "grown"
    sup = AgentSupervisor(bus, grown, **kw)
    await sup.start()
    staged = Workspace(grown, TEMPLATE).start("notes", SPEC)
    return bus, sup, staged


def ctx(d, n=1, feedback=None) -> CoderContext:
    return CoderContext(
        build_id="b1", name="notes", spec=SPEC, dir=d, round=n, fresh=n == 1, feedback=feedback, brief=brief()
    )


async def test_the_agent_gets_the_brief_the_spec_and_how_to_work(tmp_path):
    bus, sup, staged = await setup(tmp_path)
    await AgentCoder(bus, "opencode", timeout=900).write(ctx(staged))
    req = sup.requests[0]
    assert req["agent"] == "opencode" and req["name"] == "notes" and req["timeout"] == 900
    prompt = req["prompt"]
    assert "Module contract" in prompt and "Keep the last chat message" in prompt
    assert "tests/test_notes.py" in prompt and "python -m pytest -q tests" in prompt
    assert "failed at" not in prompt


async def test_a_later_round_tells_the_agent_what_failed(tmp_path):
    bus, sup, staged = await setup(tmp_path)
    fb = Feedback(stage="tests", output="x" * 9000 + "\nE   assert 'buy milk' == 'buy bread'")
    await AgentCoder(bus, "opencode").write(ctx(staged, n=2, feedback=fb))
    prompt = sup.requests[0]["prompt"]
    assert "Round 2: the last round failed at tests" in prompt and "assert 'buy milk' == 'buy bread'" in prompt
    assert "x" * 4001 not in prompt


async def test_only_a_coders_paths_come_back_and_deleted_files_go(tmp_path):
    def left(given):
        out = {k: v for k, v in given.items() if k != "tests/test_module.py"}  # the agent deleted it
        return {**out, **GOOD, "Dockerfile": "FROM evil\n", CONTRACT: "def test_nothing(): pass\n", "notes.md": "x"}

    bus, sup, staged = await setup(tmp_path, left=left)
    res = await AgentCoder(bus, "opencode").write(ctx(staged))

    assert (staged / "app" / "main.py").read_text() == GOOD["app/main.py"]
    assert not (staged / "tests" / "test_module.py").exists()
    assert "evil" not in (staged / "Dockerfile").read_text()
    assert "Written by the builder" in (staged / CONTRACT).read_text()
    assert not (staged / "notes.md").exists()
    assert "removed tests/test_module.py" in res.note and "app/main.py" in res.note and "after 42s" in res.note
    assert res.log.endswith("6 passed") and res.model == "opencode"


async def test_an_agent_that_changed_nothing_failed_the_round(tmp_path):
    bus, sup, staged = await setup(tmp_path, left=lambda given: given)
    with pytest.raises(CoderError, match="opencode exited 0 and changed nothing"):
        await AgentCoder(bus, "opencode").write(ctx(staged))


async def test_an_agent_that_failed_and_changed_nothing_stops_the_build(tmp_path):
    def untouched(given):
        return given

    bus, sup, staged = await setup(tmp_path, left=untouched)
    sup.exit_code = 1
    sup.output = "Error: Cannot connect to API: Unable to connect. Is the computer able to access the url?"
    with pytest.raises(CoderUnavailable, match="opencode exited 1 and changed nothing:\n.*Cannot connect to API"):
        await AgentCoder(bus, "opencode").write(ctx(staged))


async def test_an_agent_that_cannot_run_stops_the_build(tmp_path):
    error = "opencode cannot run: set AGENT_ENDPOINT, AGENT_MODEL for the supervisor"
    bus, sup, staged = await setup(tmp_path, reply={"ok": False, "error": error})
    with pytest.raises(CoderUnavailable, match="set AGENT_ENDPOINT"):
        await AgentCoder(bus, "opencode").write(ctx(staged))
    with pytest.raises(CoderUnavailable, match="did not answer rpc.sys.agent"):
        await AgentCoder(InMemoryBus(), "opencode", timeout=0.1, image_build=0.1).write(ctx(staged))


@pytest.mark.parametrize(
    "agents, name, reason",
    [
        ([{"name": "opencode", "ready": True}], "opencode", None),
        ([{"name": "opencode", "ready": False, "reason": "set AGENT_ENDPOINT"}], "opencode", "set AGENT_ENDPOINT"),
        ([], "goose", "the supervisor has no agent 'goose'"),
    ],
)
async def test_ready_asks_the_supervisor(tmp_path, agents, name, reason):
    bus, *_ = await setup(tmp_path, agents=agents)
    got = await AgentCoder(bus, name).ready()
    assert got == reason if reason is None else reason in got


async def test_ready_without_a_supervisor():
    assert await AgentCoder(InMemoryBus(), "opencode").ready() == "the supervisor is not answering"


async def test_a_whole_build_written_by_an_agent(tmp_path):
    bus = InMemoryBus()
    grown = tmp_path / "grown"
    sup = AgentSupervisor(bus, grown)
    await sup.start()
    record = BuildRecord(name="notes", spec=SPEC, coder="opencode")
    rounds = []

    async def on_round(rec, rnd):
        rounds.append(rnd)

    await make_pipeline(bus, grown).run(record, AgentCoder(bus, "opencode"), on_round)
    assert [(r.stage, r.passed) for r in rounds] == [("tests", True)]
    assert "6 passed" in rounds[0].output and rounds[0].log.endswith("6 passed")
    assert sup.deployed == ["notes"] and record.commit and record.model == "opencode"


async def test_a_file_too_big_to_bring_back_is_kept_not_deleted(tmp_path):
    def left(given):  # the agent's folder; the supervisor could not bring app/main.py back
        return {k: v for k, v in {**given, **GOOD}.items() if k != "app/main.py"}

    bus, sup, staged = await setup(tmp_path, left=left)
    (staged / "app" / "main.py").write_text("# as it was\n")
    sup.skipped = ["app/main.py"]
    res = await AgentCoder(bus, "opencode").write(ctx(staged))
    assert (staged / "app" / "main.py").read_text() == "# as it was\n"
    assert "removed app/main.py" not in res.note and "too big to bring back): app/main.py" in res.note


async def test_when_the_supervisor_could_not_list_everything_left_out_nothing_is_deleted(tmp_path):
    def left(given):  # app/main.py is missing from the folder that came back: maybe gone, maybe just not listed
        return {k: v for k, v in {**given, **GOOD}.items() if k != "app/main.py"}

    bus, sup, staged = await setup(tmp_path, left=left)
    (staged / "app" / "main.py").write_text("# as it was\n")
    sup.skipped, sup.skipped_more = ["venv/a.py"], 300
    res = await AgentCoder(bus, "opencode").write(ctx(staged))
    assert (staged / "app" / "main.py").read_text() == "# as it was\n" and "removed" not in res.note


async def test_a_later_round_that_errors_and_changes_nothing_only_fails_the_round(tmp_path):
    bus, sup, staged = await setup(tmp_path, left=lambda given: given)
    sup.exit_code = 1
    with pytest.raises(CoderError, match="opencode exited 1 and changed nothing"):
        await AgentCoder(bus, "opencode").write(ctx(staged, n=3, feedback=Feedback(stage="tests", output="x")))


async def test_the_agents_share_one_question_to_the_supervisor():
    from builder.coders import AgentRoster

    bus = InMemoryBus()
    asked = []

    async def agents(msg):
        asked.append(1)
        await msg.respond(
            {
                "ok": True,
                "agents": [
                    {"name": "opencode", "description": "OpenCode on your own model", "ready": True},
                    {"name": "aider", "ready": True},
                ],
            }
        )

    await bus.subscribe("rpc.sys.agents", agents)
    roster = AgentRoster(bus)
    reasons = [await AgentCoder(bus, n, roster=roster).ready() for n in ("opencode", "aider", "codex")]
    assert reasons[:2] == [None, None] and "no agent 'codex'" in reasons[2] and len(asked) == 1
    assert await AgentCoder(bus, "opencode", roster=roster).describe() == "OpenCode on your own model"
    assert len(asked) == 1  # the description comes from the same answer
