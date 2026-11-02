"""Ours, the default coder, against a scripted gateway: the stages, the forced tools, what goes back to the
model when a call is wrong, retries and caps, and prompts rebuilt from disk."""

import copy
from collections.abc import Callable

import pytest
import yaml

from builder.coders import CoderError, CoderUnavailable, MyceliumCoder
from builder.contract import CONTRACT_TEST
from builder.schemas import CoderContext, Feedback
from builder.workspace import Workspace
from mycelium_sdk import InMemoryBus
from tests.unit.builder_fakes import CODE, GOOD, SPEC, TEMPLATE, TESTS, brief

Reply = dict | Callable[[dict], dict]


def tool(name: str, args: dict, call_id: str = "c1", **extra) -> dict:
    return {
        "ok": True,
        "text": "",
        "tool_calls": [{"id": call_id, "name": name, "input": args}],
        "stop_reason": "tool_use",
        "model": "local-coder",
        "provider": "vllm",
        "cost_usd": 0.0,
        **extra,
    }


MANIFEST_ARGS = {
    "purpose": "Keeps the last note from chat so it can be read back.",
    "subscribes": ["sense.chat"],
    "emits": ["note.kept"],
    "requests": ["last"],
}
CODE_ARGS = {"files": [{"path": "app/main.py", "content": CODE}]}
TEST_ARGS = {"files": [{"path": "tests/test_notes.py", "content": TESTS.replace("WANT", "buy milk")}]}


class ScriptedGateway:
    """rpc.llm.complete answers from a script, one reply per call; rpc.llm.config describes the coder slot."""

    def __init__(self, bus: InMemoryBus, script: list[Reply], config: dict | None = None) -> None:
        self.bus = bus
        self.script = list(script)
        self.requests: list[dict] = []
        self.config = config or {
            "slots": {"coder": {"active": "vllm", "providers": {"vllm": {"key_state": "none"}}}},
        }

    async def start(self, complete: bool = True, config: bool = True) -> None:
        if complete:
            await self.bus.subscribe("rpc.llm.complete", self._complete)
        if config:
            await self.bus.subscribe("rpc.llm.config", self._config)

    async def _complete(self, msg) -> None:
        self.requests.append(copy.deepcopy(msg.data))  # as it was sent: NATS would have serialized it
        step = self.script.pop(0)
        await msg.respond(step(msg.data) if callable(step) else step)

    async def _config(self, msg) -> None:
        await msg.respond({"ok": True, **self.config})


@pytest.fixture
def staged(tmp_path):
    ws = Workspace(tmp_path, TEMPLATE)
    return ws.start("notes", SPEC)


def ctx(d, n=1, fresh=True, feedback=None) -> CoderContext:
    return CoderContext(
        build_id="b1", name="notes", spec=SPEC, dir=d, round=n, fresh=fresh, feedback=feedback, brief=brief()
    )


async def setup(script: list[Reply], **kw) -> tuple[ScriptedGateway, MyceliumCoder]:
    bus = InMemoryBus()
    gw = ScriptedGateway(bus, script)
    await gw.start()
    return gw, MyceliumCoder(bus, backoff=(0, 0), **kw)


async def test_a_fresh_round_writes_manifest_code_and_tests_through_forced_tools(staged):
    gw, coder = await setup(
        [
            tool("write_manifest", MANIFEST_ARGS),
            tool("write_files", CODE_ARGS, cost_usd=0.01),
            tool("write_files", TEST_ARGS, cost_usd=0.02),
        ]
    )
    res = await coder.write(ctx(staged))

    assert [r["tool_choice"] for r in gw.requests] == ["write_manifest", "write_files", "write_files"]
    assert all(r["slot"] == "coder" and r["cause"] == "b1" and len(r["tools"]) == 1 for r in gw.requests)
    assert "Step 1 of 3" in gw.requests[0]["messages"][0]["content"]
    assert "requests:\n- last" in gw.requests[1]["messages"][0]["content"]  # the code stage sees the manifest
    assert "def build" in gw.requests[2]["messages"][0]["content"]  # the tests stage sees the code
    assert "CONTRACT" not in gw.requests[0]["messages"][0]["content"]  # the brief is in the system prompt
    assert "Module contract" in gw.requests[0]["system"] and "hello" in gw.requests[0]["system"]
    assert len({r["system"] for r in gw.requests}) == 1  # one system part for every stage: the prefix cache keeps it

    manifest = yaml.safe_load((staged / "manifest.yaml").read_text())
    assert manifest["name"] == "notes" and manifest["requests"] == ["last"]
    assert (staged / "app" / "main.py").read_text() == CODE
    assert (staged / "tests" / "test_notes.py").exists()
    assert res.calls == 3 and res.cost_usd == 0.03 and res.model == "local-coder"
    assert "app/main.py" in res.note and "tests/test_notes.py" in res.note


async def test_a_wrong_call_goes_back_as_a_tool_result_and_the_second_is_taken(staged):
    gw, coder = await setup(
        [
            tool("write_manifest", {**MANIFEST_ARGS, "emits": ["mod.notes.kept"]}, call_id="m1"),
            tool("write_manifest", MANIFEST_ARGS),
            tool("write_files", {"files": [{"path": "Dockerfile", "content": "FROM evil"}]}, call_id="f1"),
            tool("write_files", CODE_ARGS),
            tool("write_files", {"_raw": '{"files": [{"path": "tests/test_n'}, call_id="t1"),
            tool("write_files", TEST_ARGS),
        ]
    )
    await coder.write(ctx(staged))
    assert len(gw.requests) == 6

    def last_result(req):
        block = req["messages"][-1]["content"][0]
        return block["tool_use_id"], block["content"]

    assert last_result(gw.requests[1])[0] == "m1" and "write 'kept'" in last_result(gw.requests[1])[1]
    assert last_result(gw.requests[3])[0] == "f1" and "Dockerfile" in last_result(gw.requests[3])[1]
    assert last_result(gw.requests[5])[0] == "t1" and "not valid JSON" in last_result(gw.requests[5])[1]
    assert (staged / "Dockerfile").read_text() == (TEMPLATE / "Dockerfile").read_text()


async def test_a_stage_that_never_gets_a_valid_call_fails_the_round(staged):
    no_call = {**tool("write_manifest", {}), "tool_calls": [], "stop_reason": "max_tokens", "text": "thinking..."}
    gw, coder = await setup([no_call, tool("write_manifest", {"purpose": "x"})], attempts=2)
    with pytest.raises(CoderError, match="write_manifest: no valid call after 2 tries") as e:
        await coder.write(ctx(staged))
    assert e.value.calls == 2
    assert "ran out of tokens" in gw.requests[1]["messages"][-1]["content"]


async def test_gateway_errors_are_retried_and_a_spent_budget_stops_the_build(staged):
    gw, coder = await setup(
        [
            {"ok": False, "error": "vllm: timed out after 600s"},
            tool("write_manifest", MANIFEST_ARGS),
            {"ok": False, "error": "monthly budget of $30 spent"},
        ]
    )
    with pytest.raises(CoderUnavailable, match="budget"):
        await coder.write(ctx(staged))
    assert len(gw.requests) == 3 and (staged / "manifest.yaml").exists()


async def test_a_model_that_keeps_failing_stops_the_build(staged):
    gw, coder = await setup([{"ok": False, "error": "connection refused"}] * 3)
    with pytest.raises(CoderUnavailable, match="'coder' model is not answering: connection refused"):
        await coder.write(ctx(staged))


async def test_no_gateway_stops_the_build(staged):
    coder = MyceliumCoder(InMemoryBus(), backoff=(0,))
    with pytest.raises(CoderUnavailable, match="did not answer"):
        await coder.write(ctx(staged))


async def test_the_call_cap_holds_across_rounds_of_one_build(staged):
    gw, coder = await setup([tool("write_manifest", MANIFEST_ARGS), tool("write_files", CODE_ARGS)], max_calls=2)
    with pytest.raises(CoderUnavailable, match="all 2 of its model calls"):
        await coder.write(ctx(staged))


async def test_a_fix_round_sends_the_files_from_disk_and_the_failure(staged):
    for rel, text in {**GOOD, "tests/test_contract.py": CONTRACT_TEST}.items():
        (staged / rel).parent.mkdir(parents=True, exist_ok=True)
        (staged / rel).write_text(text)
    output = "x" * 5000 + "\nE   assert 'buy milk' == 'buy bread'\n1 failed"
    fix = {
        "files": [{"path": "tests/test_notes.py", "content": TESTS.replace("WANT", "buy milk")}],
        "note": "the test expected the wrong note",
    }
    gw, coder = await setup([tool("write_files", fix), tool("write_files", fix)])
    feedback = Feedback(stage="tests", output=output)
    res = await coder.write(ctx(staged, n=2, fresh=False, feedback=feedback))
    await coder.write(ctx(staged, n=3, fresh=False, feedback=feedback))

    prompt = gw.requests[0]["messages"][0]["content"]
    assert "Round 2: the last round failed at tests" in prompt
    assert "assert 'buy milk' == 'buy bread'" in prompt and "x" * 3001 not in prompt  # the tail only
    assert "def build" in prompt and "Written by the builder" in prompt  # its code, and the test it must pass
    assert res.note == "the test expected the wrong note" and res.calls == 1
    # the next round's prompt is rebuilt from disk, not appended to: the same size
    later = gw.requests[1]["messages"][0]["content"]
    assert len(gw.requests[1]["messages"]) == 1 and abs(len(later) - len(prompt)) < 10


async def test_a_fix_may_rewrite_the_manifest_but_not_the_requirements(staged):
    gw, coder = await setup(
        [
            tool("write_files", {"files": [{"path": "requirements.txt", "content": "requests\n"}]}),
            tool("write_files", {"files": [{"path": "manifest.yaml", "content": "purpose: changed it\n"}]}),
        ]
    )
    await coder.write(ctx(staged, n=2, fresh=False, feedback=Feedback(stage="checks", output="manifest.yaml: x")))
    assert "requirements.txt" in gw.requests[1]["messages"][-1]["content"][0]["content"]
    assert (staged / "manifest.yaml").read_text() == "purpose: changed it\n"


@pytest.mark.parametrize(
    "config, complete, reason",
    [
        (None, True, None),
        ({"slots": {}}, True, "has no 'coder' slot"),
        (
            {"slots": {"coder": {"active": "claude", "providers": {"claude": {"key_state": "missing"}}}}},
            True,
            "has no key",
        ),
    ],
)
async def test_ready_says_why_it_cannot_build(config, complete, reason):
    bus = InMemoryBus()
    gw = ScriptedGateway(bus, [], config)
    await gw.start()
    got = await MyceliumCoder(bus).ready()
    assert got == reason if reason is None else reason in got


async def test_ready_without_a_gateway():
    assert await MyceliumCoder(InMemoryBus()).ready() == "the gateway is not answering"


async def test_an_error_that_will_not_pass_fails_the_round_without_retrying(staged):
    too_long = {"ok": False, "error": "vllm: 400 This model's maximum context length is 32768 tokens"}
    gw, coder = await setup([too_long])
    with pytest.raises(CoderError, match="the model refused the request: .*maximum context length") as e:
        await coder.write(ctx(staged))
    assert len(gw.requests) == 1 and e.value.calls == 1


async def test_a_cut_off_reply_goes_back_without_its_text(staged):
    cut = tool("write_manifest", {"_raw": '{"purpose": "' + "x" * 5000}, call_id="m1")
    gw, coder = await setup([cut, tool("write_manifest", MANIFEST_ARGS), tool("write_files", CODE_ARGS)])
    gw.script.append(tool("write_files", TEST_ARGS))
    await coder.write(ctx(staged))
    echoed = gw.requests[1]["messages"][1]["content"][0]
    assert echoed["type"] == "tool_use" and echoed["input"] == {}
    assert len(str(gw.requests[1]["messages"])) < 2000


async def test_retries_count_against_the_call_cap(staged):
    gw, coder = await setup([{"ok": False, "error": "vllm: timed out"}] * 3, max_calls=2)
    with pytest.raises(CoderUnavailable, match="all 2 of its model calls") as e:
        await coder.write(ctx(staged))
    assert len(gw.requests) == 2 and e.value.calls == 2


async def test_a_zero_cost_cap_lets_no_paid_call_past_the_first(staged):
    gw, coder = await setup([tool("write_manifest", MANIFEST_ARGS, cost_usd=0.4)], max_usd=0)
    with pytest.raises(CoderUnavailable, match=r"spent \$0.40 of \$0.00") as e:
        await coder.write(ctx(staged))
    assert len(gw.requests) == 1 and e.value.cost_usd == 0.4


async def test_a_fresh_round_after_a_failed_one_says_what_went_wrong(staged):
    gw, coder = await setup(
        [tool("write_manifest", MANIFEST_ARGS), tool("write_files", CODE_ARGS), tool("write_files", TEST_ARGS)]
    )
    feedback = Feedback(stage="coder", output="write_files: no valid call after 2 tries: ran out of tokens")
    await coder.write(ctx(staged, n=2, fresh=True, feedback=feedback))
    first = gw.requests[0]["messages"][0]["content"]
    assert "Round 2: the last round did not finish writing" in first and "ran out of tokens" in first


async def test_a_long_reply_without_a_tool_call_goes_back_trimmed(staged):
    prose = {**tool("write_manifest", {}), "tool_calls": [], "stop_reason": "max_tokens", "text": "x" * 20_000}
    gw, coder = await setup([prose, tool("write_manifest", MANIFEST_ARGS)])
    gw.script += [tool("write_files", CODE_ARGS), tool("write_files", TEST_ARGS)]
    await coder.write(ctx(staged))
    echoed = gw.requests[1]["messages"][1]["content"]
    assert len(echoed) < 500 and echoed.endswith("[...]")
