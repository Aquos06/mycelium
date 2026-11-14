"""scripts/bench_tools.py: the suite is sound, and a turn is scored the way the report says.

The model is a script here; the turn around it is Main's own (MainService on the stub stack).
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from bench_tools import (
    NONE,
    ArgCheck,
    Case,
    FixtureProposal,
    HistoryCall,
    HistoryTurn,
    Planner,
    Suite,
    check_suite,
    markdown,
    run_case,
    summaries,
    unique_labels,
)

from gateway.schemas import ProviderConfig
from main.tools import default_tools
from mycelium_sdk import CompletionRequest, CompletionResult, ToolCall, Usage

SUITE = Path(__file__).resolve().parents[1] / "fixtures" / "bench" / "tools.yaml"


class ScriptedProvider:
    """Answers each planner round with the next result; records what Main sent."""

    name = "script"
    model = "script-1"

    def __init__(self, *results: CompletionResult) -> None:
        self.results = list(results)
        self.requests: list[CompletionRequest] = []

    async def complete(self, req: CompletionRequest, sink=None) -> CompletionResult:
        self.requests.append(req)
        return self.results.pop(0)


def call(name: str, **args) -> CompletionResult:
    return CompletionResult(
        tool_calls=[ToolCall(id=f"c-{name}", name=name, input=args)],
        stop_reason="tool_use",
        model="script-1",
        usage=Usage(input_tokens=100, output_tokens=10),
    )


def say(text: str) -> CompletionResult:
    return CompletionResult(text=text, model="script-1", usage=Usage(input_tokens=120, output_tokens=5))


def planner(*results: CompletionResult) -> Planner:
    cfg = ProviderConfig(kind="ollama", model="script-1")
    return Planner("script", cfg, ScriptedProvider(*results), timeout=5)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def suite() -> Suite:
    return Suite.load(SUITE)


def case(suite: Suite, case_id: str):
    return next(c for c in suite.cases if c.id == case_id)


# ---- the suite ---------------------------------------------------------------------------------------


def test_suite_is_sound(suite):
    assert check_suite(suite, default_tools()) == []


def test_twenty_cases_for_every_tool_and_for_none(suite):
    per = Counter(c.expect for c in suite.cases)
    for expected in [*default_tools().names, NONE]:
        assert per[expected] >= 20, f"{expected}: {per[expected]} cases"


def test_a_case_naming_a_missing_note_is_refused(suite):
    raw = suite.model_dump(mode="json")
    raw["cases"][0]["pack"] = ["nobody"]
    with pytest.raises(ValueError, match="no notes"):
        Suite.model_validate(raw)


def test_an_args_check_on_a_field_the_tool_lacks_is_reported(suite):
    bad = suite.model_copy(deep=True)
    bad.cases[0].args = {"nonsense": ArgCheck(equals=["x"])}
    assert any("has no argument ['nonsense']" in p for p in check_suite(bad, default_tools()))


def test_also_or_avoid_naming_a_tool_main_lacks_is_reported(suite):
    bad = suite.model_copy(deep=True)
    bad.cases[0].avoid = ["teleport"]
    assert any("does not have: ['teleport']" in p for p in check_suite(bad, default_tools()))


async def test_also_and_avoid_decide_a_pass(suite):
    logged = Case(id="log", msg="spent 85 on breakfast", expect="remember", modules=["hello"])
    script = (call("remember", note="expenses", fact="breakfast 85"), say("Saved: breakfast 85."))
    wants_offer = logged.model_copy(update={"also": ["propose_module"]})
    row = await run_case(suite, wants_offer, planner(*script), default_tools(), suite.today)
    assert row.tools == ["remember"] and not row.passed  # remembered, but offered no module
    no_offer = logged.model_copy(update={"avoid": ["propose_module"]})
    row = await run_case(suite, no_offer, planner(*script), default_tools(), suite.today)
    assert row.passed and not row.claim_check


async def test_offered_proposals_and_a_dated_history_with_calls_reach_main(suite):
    c = Case(
        id="offered",
        msg="lunch was 120",
        expect="remember",
        modules=["hello"],
        proposals=[FixtureProposal(name="expenses", purpose="Tracks spending.")],
        history=[
            HistoryTurn(role="user", text="today i spent 112 on dinner", day=date(2026, 10, 27)),
            HistoryTurn(
                role="assistant", text="Logged: 112.", calls=[HistoryCall(name="remember", input={"note": "expenses"})]
            ),
        ],
    )
    p = planner(say("ok"))
    await run_case(suite, c, p, default_tools(), suite.today)
    sent = p.provider.requests[0]  # type: ignore[attr-defined]
    assert "- expenses: Tracks spending. (offered 2026-11-03, waiting for his Build it" in sent.system
    assert sent.messages[0].content == "[Tue 2026-10-27] today i spent 112 on dinner"
    assert sent.messages[1].content[0].name == "remember" and sent.messages[3].content == "Logged: 112."


def test_arg_checks():
    assert ArgCheck.model_validate("mei").check("MEI")
    assert ArgCheck.model_validate(["mei", "lin"]).check("lin")
    assert not ArgCheck.model_validate("mei").check("people/mei")
    assert ArgCheck.model_validate({"has": ["tainan"]}).check("is moving to Tainan in December")
    assert ArgCheck.model_validate({"has": ["lin"]}).check(["Mei", "Lin"])  # a list is checked as its JSON text
    assert not ArgCheck.model_validate({"has": ["x"]}).check(None)


# ---- a turn, scored ---------------------------------------------------------------------------------------


async def test_right_tool_first_with_the_right_arguments(suite):
    p = planner(call("remember", note="people/mei.md", fact="birthday is March 3"), say("Saved."))
    row = await run_case(suite, case(suite, "rem-mei-birthday"), p, default_tools(), suite.today)
    assert row.passed and row.first and row.args_ok  # the path in `note` is normalised to the slug, as Main does
    assert (row.got, row.tools, row.rounds, row.invalid) == ("remember", ["remember"], 2, 0)
    assert row.tokens_in == 220 and row.reply == '"Saved."'


async def test_main_got_the_case_context(suite):
    p = planner(say("Tainan, in December."))
    await run_case(suite, case(suite, "none-mei-moving"), p, default_tools(), suite.today)
    system = p.provider.requests[0].system  # type: ignore[attr-defined]
    assert "people/mei.md" in system and "moving to Tainan" in system  # the pack
    assert "expenses: Tracks spending" in system and "climbing.sessions" in system  # the default modules
    assert "Tuesday 2026-11-03" in system


async def test_a_tool_where_none_was_expected_fails(suite):
    p = planner(call("recall", query="mei"), say("Tainan."))
    row = await run_case(suite, case(suite, "none-mei-moving"), p, default_tools(), suite.today)
    assert not row.passed and row.got == "recall"


async def test_right_tool_after_another_passes_but_not_first(suite):
    p = planner(call("recall", query="expenses"), call("ask_module", module="expenses", action="summary"), say("3420"))
    row = await run_case(suite, case(suite, "mod-spend-week"), p, default_tools(), suite.today)
    assert row.passed and not row.first and row.args_ok
    assert row.tools == ["recall", "ask_module"]


async def test_wrong_arguments_and_rejected_calls_are_counted(suite):
    p = planner(
        call("ask_module", module="Expenses!", action="summary"),  # Main rejects it, the model retries
        call("ask_module", module="hello", action="stats"),
        say("14 messages"),
    )
    row = await run_case(suite, case(suite, "mod-spend-week"), p, default_tools(), suite.today)
    assert row.passed and row.invalid == 1
    assert row.args_ok is False  # the valid call asked the wrong module


async def test_ask_ends_the_turn_and_its_choices_are_checked(suite):
    p = planner(call("ask", text="Whose job?", choices=["Mei", "Lin"]))
    row = await run_case(suite, case(suite, "ask-she-job"), p, default_tools(), suite.today)
    assert row.passed and row.first and row.args_ok and row.rounds == 1


async def test_history_reaches_the_model(suite):
    p = planner(call("ask", text="Who?", choices=["Jason", "Kevin"]))
    await run_case(suite, case(suite, "ask-history-promoted"), p, default_tools(), suite.today)
    sent = p.provider.requests[0].messages  # type: ignore[attr-defined]
    assert [m.content for m in sent[:2]] == [
        "[Tue 2026-11-03] had lunch with jason and kevin today",  # the suite's today: "today" in it is that day
        "Nice! Want me to remember anything from it?",
    ]


async def test_a_model_that_fails_is_an_error_not_a_pass(suite):
    class Down(ScriptedProvider):
        async def complete(self, req, sink=None):
            from gateway.providers import ProviderError

            raise ProviderError("vllm: ConnectError")

    p = Planner("down", ProviderConfig(kind="ollama", model="m"), Down(), timeout=5)  # type: ignore[arg-type]
    row = await run_case(suite, case(suite, "none-thanks"), p, default_tools(), suite.today)
    assert not row.passed and row.got == "error" and "ConnectError" in (row.error or "")


async def test_the_report_counts_per_class(suite):
    rows = [
        await run_case(suite, case(suite, "rem-mei-birthday"), planner(say("ok")), default_tools(), suite.today),
        await run_case(
            suite, case(suite, "none-thanks"), planner(say("You're welcome!")), default_tools(), suite.today
        ),
    ]
    by = {s.expect: s for s in summaries(rows)}
    assert (by["remember"].passed, by["none"].passed, by["all"].passed, by["all"].n) == (0, 1, 1, 2)
    report = markdown(rows, suite, suite.today)
    assert "| rem-mei-birthday | mei's birthday is march 3, remember that | remember | none |" in report
    assert "| **all** | 1/2 (50%) |" in report


def test_the_same_provider_twice_keeps_two_labels():
    planners = unique_labels([planner(), planner(), planner()])
    assert [p.label for p in planners] == ["script", "script#2", "script#3"]


async def test_a_cases_reminders_and_the_suites_clock_reach_main(suite):
    c = Case(id="set", msg="what reminders do I have?", expect="none", modules=["hello"], reminders=["rent01"])
    p = planner(say("ok"))
    await run_case(suite, c, p, default_tools(), suite.today)
    system = p.provider.requests[0].system  # type: ignore[attr-defined]
    assert "Today is Tuesday 2026-11-03 (Asia/Taipei)." in system and system.endswith("\n\nIt is 14:00 now.")
    assert "- rent01 Fri 2026-11-06 09:00, every month: Time to pay the rent." in system
