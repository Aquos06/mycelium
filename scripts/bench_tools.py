#!/usr/bin/env python3
"""Benchmark Main's tool calling: for each message, does the planner call the right tool (or none), first,
with the right arguments, and how long does the turn take.

    set -a; source .env; set +a
    .venv/bin/python scripts/bench_tools.py --cases tests/fixtures/bench/tools.yaml             # the planner slot
    .venv/bin/python scripts/bench_tools.py --cases ... --provider vllm --provider claude       # compare
    .venv/bin/python scripts/bench_tools.py --cases ... --provider ollama=http://localhost:11434/v1=qwen2.5:14b
    .venv/bin/python scripts/bench_tools.py --cases ... --only ask,none --out bench.md --json bench.json

Each case runs Main's own turn (main.service.MainService) on an in-memory bus, so the prompt, the tools offered,
the validation of every call and the rounds are exactly Main's. The bus around it is a stub: memory answers
recall with the case's pack (and an empty result for the `recall` tool), remember with ok, rpc.sys.list with the
case's modules, and each module's request with its fixture reply. Only the planner calls leave the process,
through the gateway's own provider class built from services/gateway/providers.yaml, so nothing is written to
the vault, no trace reaches the stack, and a case can run many times.

--provider NAME[=ENDPOINT[=MODEL]] picks a provider of the planner slot by its name in providers.yaml (vllm,
ollama, claude, openai) and optionally overrides where it lives and which model; repeatable. Without it, the
slot's active provider (PLANNER_PROVIDER) is measured. Cloud kinds read their key from the environment.

Per case: the tools called in order, whether the expected one was among them (`none`: no tool at all), whether
it came first, whether its arguments pass the case's checks, calls Main rejected as invalid, rounds, latency.
Per provider and expected class: those as counts, plus p50/p95 turn latency and a confusion table of the first
decision.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

REPO = Path(__file__).resolve().parents[1]
for p in (REPO / "services", REPO / "sdk"):
    sys.path.insert(0, str(p))

from gateway.providers import Provider, ProviderError, build_provider  # noqa: E402
from gateway.schemas import GatewayConfig, ProviderConfig  # noqa: E402
from main.schemas import PlanTrace  # noqa: E402
from main.service import MainService  # noqa: E402
from main.thread import Thread, ThreadStore, Turn  # noqa: E402
from main.tools import ToolRegistry, default_tools  # noqa: E402
from mycelium_sdk import (  # noqa: E402
    CompletionReply,
    CompletionRequest,
    InMemoryBus,
    InMemoryKV,
    Message,
    Role,
)

NONE = "none"  # the expected class for "answer without a tool"
ERROR = "error"  # what the first decision is when the turn failed before any call
CHANNEL = "web"
PROVIDERS_YAML = REPO / "services" / "gateway" / "providers.yaml"


# ---- the cases ----------------------------------------------------------------------------------------


class NoteLine(BaseModel):
    """One line of the recall pack, as memory sends it (memory.schemas.RecallItem)."""

    note: str
    why: str
    excerpt: str = ""


class FixtureModule(BaseModel):
    purpose: str
    requests: list[str] = Field(min_length=1)
    subscribes: list[str] = Field(default_factory=list)  # Main's prompt says what a module listens to
    reply: dict[str, Any] = Field(default_factory=dict)  # what every request of the module answers


class ArgCheck(BaseModel):
    """`equals`: the value is one of these; `has`: its text contains one of these. Case-insensitive."""

    equals: list[str] = Field(default_factory=list)
    has: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        """`note: mei` and `note: [mei, lin]` mean equals."""
        if isinstance(data, str | int | float):
            return {"equals": [str(data)]}
        if isinstance(data, list):
            return {"equals": [str(v) for v in data]}
        return data

    @field_validator("equals", "has", mode="before")
    @classmethod
    def _strings(cls, v: Any) -> Any:
        return [str(x) for x in v] if isinstance(v, list) else v

    def check(self, value: Any) -> bool:
        text = "" if value is None else value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        text = text.strip().lower()
        if self.equals and text not in {e.lower() for e in self.equals}:
            return False
        return not self.has or any(h.lower() in text for h in self.has)


class HistoryTurn(BaseModel):
    role: Role
    text: str


class Case(BaseModel):
    id: str = Field(min_length=1)
    msg: str = Field(min_length=1)
    expect: str  # a tool name, or "none"
    pack: list[str] = Field(default_factory=list)  # names under `notes`
    modules: list[str] | None = None  # names under `modules`; None: the suite's default_modules
    history: list[HistoryTurn] = Field(default_factory=list)
    args: dict[str, ArgCheck] = Field(default_factory=dict)


class Suite(BaseModel):
    today: date
    tz: str = "Asia/Taipei"
    modules: dict[str, FixtureModule] = Field(default_factory=dict)
    default_modules: list[str] = Field(default_factory=list)
    notes: dict[str, NoteLine] = Field(default_factory=dict)
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def _names_resolve(self) -> Suite:
        ids = Counter(c.id for c in self.cases)
        if dupes := [i for i, n in ids.items() if n > 1]:
            raise ValueError(f"duplicate case ids: {dupes}")
        for name in self.default_modules:
            if name not in self.modules:
                raise ValueError(f"default_modules: no module {name!r}")
        for c in self.cases:
            if missing := [n for n in c.pack if n not in self.notes]:
                raise ValueError(f"{c.id}: no notes {missing}")
            if missing := [m for m in (c.modules or []) if m not in self.modules]:
                raise ValueError(f"{c.id}: no modules {missing}")
        return self

    @classmethod
    def load(cls, path: str | Path) -> Suite:
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def pack_for(self, case: Case) -> list[NoteLine]:
        return [self.notes[n] for n in case.pack]

    def modules_for(self, case: Case) -> dict[str, FixtureModule]:
        names = self.default_modules if case.modules is None else case.modules
        return {n: self.modules[n] for n in names}


def check_suite(suite: Suite, tools: ToolRegistry) -> list[str]:
    """Problems that make a case unscorable: an unknown expected tool, or an args check on a field it lacks."""
    problems = []
    for c in suite.cases:
        if c.expect == NONE:
            if c.args:
                problems.append(f"{c.id}: `none` takes no args checks")
            continue
        tool = tools.get(c.expect)
        if tool is None:
            problems.append(f"{c.id}: Main has no tool {c.expect!r}")
            continue
        fields = set(tool.args.model_fields)
        if unknown := sorted(set(c.args) - fields):
            problems.append(f"{c.id}: {c.expect} has no argument {unknown}")
    return problems


# ---- the stack around Main -----------------------------------------------------------------------------


class StubStack:
    """What memory, the supervisor and the modules answer for one case. Nothing leaves the process."""

    def __init__(self, suite: Suite, case: Case) -> None:
        self.pack = suite.pack_for(case)
        self.modules = suite.modules_for(case)
        self.paths = {Path(n.note).stem: n.note for n in suite.notes.values()}  # slug -> the note's path
        self._recalls = 0

    async def attach(self, bus: InMemoryBus) -> None:
        await bus.subscribe("rpc.memory.recall", self._recall)
        await bus.subscribe("rpc.memory.remember", self._remember)
        await bus.subscribe("rpc.sys.list", self._list)
        await bus.subscribe("rpc.build.list", self._builds)  # propose_module checks the name is free
        await bus.subscribe("rpc.mod.>", self._module)

    async def _recall(self, msg: Message) -> None:
        # Main's own recall of the whole message comes first and gets the case's pack; every later one is the
        # `recall` tool, which finds nothing more (the case is about whether it is called, not what it finds)
        self._recalls += 1
        items = self.pack if self._recalls == 1 else []
        await msg.respond({"ok": True, "items": [i.model_dump() for i in items], "used": {}})

    async def _remember(self, msg: Message) -> None:
        note = str(msg.data.get("note") or "note")
        known = self.paths.get(note)
        path = known or f"{msg.data.get('type') or 'things'}/{note}.md"
        await msg.respond({"ok": True, "path": path, "created": known is None})

    async def _list(self, msg: Message) -> None:
        rows = [
            {"name": n, "status": "running", "manifest": {"name": n, **m.model_dump(exclude={"reply"})}}
            for n, m in self.modules.items()
        ]
        await msg.respond({"ok": True, "modules": rows})

    async def _builds(self, msg: Message) -> None:
        await msg.respond({"ok": True, "builds": []})

    async def _module(self, msg: Message) -> None:
        _, _, name, action = (msg.subject.split(".", 3) + ["", "", "", ""])[:4]
        module = self.modules.get(name)
        if module is None or action not in module.requests:
            await msg.respond({"ok": False, "error": f"no responders for {msg.subject}"})
            return
        await msg.respond({"ok": True, **module.reply})


class Planner:
    """rpc.llm.complete, answered by one provider the way the gateway would (minus budget and traces)."""

    def __init__(self, label: str, cfg: ProviderConfig, provider: Provider, timeout: float) -> None:
        self.label = label
        self.cfg = cfg
        self.provider = provider
        self.timeout = timeout

    async def handle(self, msg: Message) -> None:
        req = CompletionRequest.model_validate(msg.data)
        try:
            result = await asyncio.wait_for(self.provider.complete(req), timeout=req.timeout or self.timeout)
        except TimeoutError:
            await msg.respond({"ok": False, "error": f"{self.label}: timed out after {req.timeout or self.timeout:g}s"})
            return
        except ProviderError as e:
            await msg.respond({"ok": False, "error": str(e)})
            return
        except Exception as e:  # a bug in a provider must show as a failed case, not end the run
            await msg.respond({"ok": False, "error": f"{type(e).__name__}: {e}"})
            return
        cost = self.cfg.cost(result.usage.input_tokens, result.usage.output_tokens)  # as the gateway bills it
        reply = CompletionReply(**result.model_dump(), provider=self.label, cost_usd=cost)
        await msg.respond({"ok": True, **reply.model_dump(mode="json")})


# ---- one case --------------------------------------------------------------------------------------------


class Call(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    valid: bool  # Main's own argument model accepted it
    parsed: dict[str, Any] | None = None  # the arguments after that model's normalising (slugs, prefixes)


class Row(BaseModel):
    """One provider on one case."""

    provider: str
    model: str = ""
    case: str
    expect: str
    got: str  # the first decision: the first tool called, `none`, or `error`
    tools: list[str] = Field(default_factory=list)  # every call in order
    calls: list[Call] = Field(default_factory=list)  # with their arguments, for the JSON
    passed: bool = False  # the expected tool was called (`none`: nothing was, and the turn did not fail)
    first: bool = False  # ... and it was the first call
    args_ok: bool | None = None  # its first valid call passes the checks; None: no checks, or never called
    invalid: int = 0  # calls Main rejected (unknown tool, bad arguments)
    rounds: int = 0
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    reply: str = ""
    error: str | None = None


def score(case: Case, trace: PlanTrace, tools: ToolRegistry, provider: str, model: str) -> Row:
    calls: list[Call] = []
    for t in trace.tools:
        tool = tools.get(t.name)
        parsed = None
        if tool is not None:
            try:
                parsed = tool.parse(t.input).model_dump(mode="json")
            except ValidationError:
                parsed = None
        calls.append(Call(name=t.name, input=t.input, valid=parsed is not None, parsed=parsed))
    names = [c.name for c in calls]
    got = names[0] if names else (ERROR if trace.error else NONE)
    if case.expect == NONE:
        passed = not names and not trace.error
    else:
        passed = case.expect in names
    args_ok = None
    if case.args and passed:
        hit = next((c for c in calls if c.name == case.expect and c.valid), None)
        args_ok = hit is not None and all(chk.check((hit.parsed or {}).get(f)) for f, chk in case.args.items())
    reply = trace.output.model_dump(mode="json")
    usage = [c.usage for c in trace.llm_calls if c.usage]
    return Row(
        provider=provider,
        model=model,
        case=case.id,
        expect=case.expect,
        got=got,
        tools=names,
        calls=calls,
        passed=passed,
        first=got == case.expect,
        args_ok=args_ok,
        invalid=sum(not c.valid for c in calls),
        rounds=trace.rounds,
        latency_ms=trace.latency_ms,
        tokens_in=sum(u.input_tokens for u in usage),
        tokens_out=sum(u.output_tokens for u in usage),
        cost_usd=trace.cost_usd,
        reply=json.dumps(reply.get("say") or reply.get("ask"), ensure_ascii=False)[:240],
        error=trace.error,
    )


async def run_case(suite: Suite, case: Case, planner: Planner, tools: ToolRegistry, today: date) -> Row:
    bus = InMemoryBus()
    store = ThreadStore(InMemoryKV())
    if case.history:
        turns = [Turn(role=h.role, text=h.text, ts=f"{today.isoformat()}T12:00:00+08:00") for h in case.history]
        await store.append(Thread(channel=CHANNEL, thread=case.id), *turns)
    await StubStack(suite, case).attach(bus)
    await bus.subscribe("rpc.llm.complete", planner.handle)
    main = MainService(bus, store, today=lambda: today, tz=suite.tz, llm_timeout=planner.timeout)
    await main.start()
    await bus.publish("sense.chat", {"id": f"bench-{case.id}", "channel": CHANNEL, "thread": case.id, "text": case.msg})
    await main.drain()
    traces = bus.events("trace.plan")
    if not traces:
        error = "Main published no trace.plan"
        return Row(
            provider=planner.label, model=planner.cfg.model, case=case.id, expect=case.expect, got=ERROR, error=error
        )
    return score(case, PlanTrace.model_validate(traces[-1][1]), tools, planner.label, planner.cfg.model)


# ---- the report -------------------------------------------------------------------------------------------


class Summary(BaseModel):
    provider: str
    model: str
    expect: str  # a class, or "all"
    n: int
    passed: int
    first: int
    args_checked: int  # passed cases with argument checks
    args_ok: int
    invalid: int
    errors: int
    rounds_mean: float
    p50_s: float
    p95_s: float
    cost_usd: float


def summarise(provider: str, model: str, expect: str, rows: list[Row]) -> Summary:
    lat = sorted(r.latency_ms / 1000 for r in rows) or [0.0]
    return Summary(
        provider=provider,
        model=model,
        expect=expect,
        n=len(rows),
        passed=sum(r.passed for r in rows),
        first=sum(r.first for r in rows),
        args_checked=sum(r.args_ok is not None for r in rows),
        args_ok=sum(r.args_ok is True for r in rows),
        invalid=sum(r.invalid for r in rows),
        errors=sum(r.error is not None for r in rows),
        rounds_mean=round(statistics.fmean(r.rounds for r in rows), 2) if rows else 0.0,
        p50_s=round(statistics.median(lat), 1),
        p95_s=round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 1),
        cost_usd=round(sum(r.cost_usd for r in rows), 4),
    )


def classes_of(rows: list[Row]) -> list[str]:
    order = [*sorted({r.expect for r in rows} - {NONE}), NONE]
    return [c for c in order if any(r.expect == c for r in rows)]


def summaries(rows: list[Row]) -> list[Summary]:
    out = []
    for provider in dict.fromkeys(r.provider for r in rows):
        mine = [r for r in rows if r.provider == provider]
        model = mine[0].model
        for cls in classes_of(mine):
            out.append(summarise(provider, model, cls, [r for r in mine if r.expect == cls]))
        out.append(summarise(provider, model, "all", mine))
    return out


def pct(k: int, n: int) -> str:
    return f"{k}/{n} ({round(100 * k / n)}%)" if n else "-"


def markdown(rows: list[Row], suite: Suite, today: date) -> str:
    lines = [f"# Main tool calling: {len({r.case for r in rows})} cases, today {today.isoformat()}", ""]
    for provider in dict.fromkeys(r.provider for r in rows):
        mine = [r for r in rows if r.provider == provider]
        classes = classes_of(mine)
        lines += [f"## {provider} ({mine[0].model})", ""]
        lines += [
            "| expect | right tool | first call | args ok | invalid calls | errors | rounds | p50 | p95 | cost |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in summaries(mine):
            name = f"**{s.expect}**" if s.expect == "all" else s.expect
            lines.append(
                f"| {name} | {pct(s.passed, s.n)} | {pct(s.first, s.n)} | {pct(s.args_ok, s.args_checked)} "
                f"| {s.invalid} | {s.errors} | {s.rounds_mean} | {s.p50_s}s | {s.p95_s}s | ${s.cost_usd} |"
            )
        cols = [*classes, ERROR]
        lines += ["", "First decision (rows: expected, columns: what Main did first):", ""]
        lines += ["| expected | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        for cls in classes:
            counts = Counter(r.got for r in mine if r.expect == cls)
            other = sum(v for k, v in counts.items() if k not in cols)
            cells = [str(counts.get(c, 0) or "") for c in cols]
            lines.append(f"| {cls} | " + " | ".join(cells) + " |" + (f" +{other} other" if other else ""))
        misses = [r for r in mine if not r.passed or r.args_ok is False]
        if misses:
            msgs = {c.id: c.msg for c in suite.cases}
            lines += ["", "Misses:", "", "| case | message | expect | tools called | reply |", "|---|---|---|---|---|"]
            for r in misses:
                called = " → ".join(r.tools) or "none"
                if r.passed:
                    called += " (args off)"
                reply = (r.error or r.reply).replace("|", "/").replace("\n", " ")
                lines.append(f"| {r.case} | {msgs.get(r.case, '')} | {r.expect} | {called} | {reply[:120]} |")
        lines.append("")
    return "\n".join(lines)


# ---- the run --------------------------------------------------------------------------------------------------


def build_planner(spec: str | None, providers_yaml: Path, timeout: float) -> Planner:
    """NAME[=ENDPOINT[=MODEL]] from the planner slot of providers.yaml; None: the slot's active provider."""
    slot = GatewayConfig.from_yaml(providers_yaml, os.environ).slots["planner"]
    name, _, rest = (spec or slot.active).partition("=")
    endpoint, _, model = rest.partition("=")
    if name not in slot.providers:
        raise SystemExit(f"--provider {name!r}: the planner slot has {', '.join(slot.providers)}")
    cfg = slot.providers[name]
    update = {k: v for k, v in (("endpoint", endpoint), ("model", model)) if v}
    cfg = cfg.model_copy(update=update) if update else cfg
    provider = build_provider(name, cfg, os.environ)
    label = name if not update else f"{name}:{model or endpoint}"  # two of one kind compared stay apart
    return Planner(label, cfg, provider, timeout)  # type: ignore[arg-type]


def unique_labels(planners: list[Planner]) -> list[Planner]:
    """The report groups rows by label: the same --provider twice gets #2, #3."""
    seen: Counter[str] = Counter()
    for p in planners:
        seen[p.label] += 1
        if seen[p.label] > 1:
            p.label = f"{p.label}#{seen[p.label]}"
    return planners


async def run(args: argparse.Namespace) -> int:
    suite = Suite.load(args.cases)
    tools = default_tools()
    if problems := check_suite(suite, tools):
        print("\n".join(problems), file=sys.stderr)
        return 2
    today = args.today or suite.today
    cases = [
        c for c in suite.cases if (not args.only or c.expect in args.only) and (not args.case or c.id in args.case)
    ]
    if not cases:
        print("no cases match --only / --case", file=sys.stderr)
        return 2
    specs = args.provider or [None]
    planners = unique_labels([build_planner(s, Path(args.providers_yaml), args.timeout) for s in specs])
    gate = asyncio.Semaphore(args.concurrency)
    rows: list[Row] = []
    total = len(cases) * len(planners)

    async def one(planner: Planner, case: Case) -> None:
        async with gate:
            t0 = time.monotonic()
            row = await run_case(suite, case, planner, tools, today)
        rows.append(row)
        mark = "ok  " if row.passed and row.args_ok is not False else "MISS"
        took = time.monotonic() - t0
        tools_called = " → ".join(row.tools) or NONE
        print(
            f"[{len(rows):>3}/{total}] {mark} {planner.label:<8} {case.id:<24} expect {case.expect:<10} "
            f"got {tools_called} ({took:.1f}s)" + (f" error: {row.error}" if row.error else ""),
            file=sys.stderr,
            flush=True,
        )

    await asyncio.gather(*(one(p, c) for p in planners for c in cases))
    order = {(p.label, c.id): i for i, (p, c) in enumerate((p, c) for p in planners for c in cases)}
    rows.sort(key=lambda r: order[(r.provider, r.case)])

    report = markdown(rows, suite, today)
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps([r.model_dump() for r in rows], ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True, help="the suite (tests/fixtures/bench/tools.yaml)")
    ap.add_argument("--provider", action="append", help="NAME[=ENDPOINT[=MODEL]] of the planner slot; repeatable")
    ap.add_argument("--providers-yaml", default=str(PROVIDERS_YAML))
    ap.add_argument("--only", type=lambda s: set(s.split(",")), help="expected classes: remember,recall,...,none")
    ap.add_argument("--case", action="append", help="one case id; repeatable")
    ap.add_argument("--today", type=date.fromisoformat, help="default: the suite's `today`")
    ap.add_argument("--concurrency", type=int, default=4, help="cases in flight at once")
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds per planner round")
    ap.add_argument("--out", help="write the markdown report here too")
    ap.add_argument("--json", help="write every row as JSON here")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
