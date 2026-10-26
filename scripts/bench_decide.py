#!/usr/bin/env python3
"""Benchmark the scorers behind rpc.llm.decide: which one ranks the right note first, how fast, at what cost.

    .venv/bin/python scripts/bench_decide.py --vault tests/fixtures/vault --questions tests/fixtures/bench/decide.yaml \\
        --scorer tei=http://localhost:8102 --scorer vllm=http://192.168.0.107:8000/v1 --scorer claude --scorer embed

    .venv/bin/python scripts/bench_decide.py --db --questions bench_live.yaml --scorer ...      # the live index

Each scorer is the gateway's own provider class (gateway.providers.decide), built the way providers.yaml would,
so what is measured is what the gateway runs. The candidates are memory's catalogue (memory.decide.catalogue):
every note, the period summaries and the recent day summaries, one line each. Per question and scorer: the rank
of the expected note, its score, the margin to the best wrong one, the latency of the call, the cost. Per
scorer: top-1, hit@3, MRR, mean margin, p50/p95 latency, total cost, failures.

--scorer NAME=ENDPOINT[=MODEL]. NAME picks the kind: tei (bge-reranker-v2-m3 on TEI), vllm, ollama, claude,
openai (chat models through the forced tool; cloud kinds read their key from the environment, load .env first). `--scorer embed` is the baseline the decide step
replaces: cosine between the question's vector and each candidate's, through the stack's rpc.llm.embed (NATS_URL).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[1]
for p in (REPO / "services", REPO / "sdk"):
    sys.path.insert(0, str(p))

from gateway.providers import ProviderError, build_provider  # noqa: E402
from gateway.schemas import DecideRequest, ProviderConfig  # noqa: E402
from memory.decide import catalogue  # noqa: E402
from memory.index import InMemoryIndex, PostgresIndex  # noqa: E402
from memory.indexer import reindex  # noqa: E402
from memory.vault import Vault  # noqa: E402
from mycelium_sdk.db import make_engine  # noqa: E402

KIND_DEFAULTS: dict[str, tuple[str, str, dict[str, Any]]] = {
    # name prefix -> (kind, default model, extra_body)
    "tei": ("tei", "BAAI/bge-reranker-v2-m3", {}),
    "vllm": ("vllm", "/model", {}),
    "ollama": ("ollama", "qwen2.5:14b", {}),
    "claude": ("claude", "claude-haiku-5-5", {}),
    "openai": ("openai", "gpt-5-mini", {}),
}
PRICES = {"claude": (1.0, 5.0), "openai": (0.25, 2.0)}  # USD per M tokens, the providers.yaml figures


class Question(BaseModel):
    q: str
    expect: list[str]
    hard: bool = False

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Question:
        expect = raw["expect"]
        return cls(q=raw["q"], expect=[expect] if isinstance(expect, str) else list(expect), hard=bool(raw.get("hard")))


class Row(BaseModel):
    """One scorer on one question."""

    scorer: str
    model: str = ""
    q: str
    rank: int | None = None  # 1 = the expected note scored highest; None = failed
    score: float | None = None  # the expected note's score
    margin: float | None = None  # expected minus the best wrong one; positive = separable by a threshold
    top: str | None = None  # what came first
    latency_ms: int = 0
    cost_usd: float = 0.0
    error: str | None = None


class Summary(BaseModel):
    scorer: str
    model: str
    n: int
    top1: float
    hit3: float
    mrr: float
    margin: float | None
    p50_ms: int
    p95_ms: int
    cost_usd: float
    failures: int


class EmbedCosineScorer:
    """The embedding rung as a scorer: one rpc.llm.embed for the question and every candidate, cosine per candidate."""

    name = "embed"
    model = "embed slot"

    def __init__(self, nats_url: str) -> None:
        self.nats_url = nats_url

    async def decide(self, req: DecideRequest) -> Any:
        from gateway.schemas import DecideResult, Score, Usage
        from mycelium_sdk import NatsBus

        bus = NatsBus(self.nats_url, name="bench")
        await bus.connect()
        try:
            texts = [req.query, *(c.text for c in req.candidates)]
            reply = await bus.request("rpc.llm.embed", {"slot": "embed", "texts": texts, "timeout": 60}, timeout=65)
        finally:
            await bus.close()
        if not reply.get("ok"):
            raise ProviderError(str(reply.get("error")))
        q, *vs = reply["vectors"]
        self.model = str(reply.get("model") or self.model)

        def cos(a, b):
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            na, nb = sum(x * x for x in a) ** 0.5, sum(y * y for y in b) ** 0.5
            return dot / (na * nb) if na and nb else 0.0

        scores = [Score(id=c.id, score=min(1.0, max(0.0, cos(q, v)))) for c, v in zip(req.candidates, vs, strict=True)]
        return DecideResult(scores=scores, model=self.model, usage=Usage())


def parse_scorer(spec: str) -> tuple[str, Any]:
    name, _, rest = spec.partition("=")
    endpoint, _, model = rest.partition("=")
    if name == "embed":
        scorer = EmbedCosineScorer(endpoint or os.environ.get("NATS_URL", "nats://localhost:4222"))
        return name, (ProviderConfig(kind="ollama", model="embed slot"), scorer)
    kind, default_model, extra = KIND_DEFAULTS.get(name) or KIND_DEFAULTS[name.split("-")[0]]
    price_in, price_out = PRICES.get(kind, (0.0, 0.0))
    cfg = ProviderConfig(
        kind=kind,
        model=model or default_model,
        endpoint=endpoint or None,
        extra_body=extra,
        price_in_per_m=price_in,
        price_out_per_m=price_out,
        max_tokens=4096,
    )
    return name, (cfg, build_provider(name, cfg, os.environ, task="decide"))


async def load_candidates(args: argparse.Namespace, today: date) -> list[dict[str, str]]:
    if args.vault:
        index: Any = InMemoryIndex()
        await reindex(Vault(Path(args.vault)), index)
        rows = await catalogue(index, today, args.recent_days)
    else:
        dsn = os.environ.get("MEMORY_DATABASE_URL") or os.environ["DATABASE_URL"]
        engine = make_engine(dsn, pool_size=2)
        index = PostgresIndex(engine, schema=args.schema)
        rows = await catalogue(index, today, args.recent_days)
        await engine.dispose()
    return [{"id": c.path, "text": c.text} for c in rows]


async def run_one(
    name: str, cfg: ProviderConfig, provider: Any, q: Question, cands: list[dict[str, str]], timeout: float
) -> Row:
    req = DecideRequest(query=q.q, candidates=cands, timeout=timeout)
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(provider.decide(req), timeout=timeout)
    except (ProviderError, TimeoutError, Exception) as e:  # noqa: BLE001
        return Row(
            scorer=name, q=q.q, latency_ms=int((time.monotonic() - t0) * 1000), error=f"{type(e).__name__}: {e}"[:160]
        )
    ms = int((time.monotonic() - t0) * 1000)
    ranked = result.ranked()
    by_id = {s.id: s.score for s in ranked}
    best_expected = max(q.expect, key=lambda p: by_id.get(p, -1.0))
    rank = next((i for i, s in enumerate(ranked, 1) if s.id in q.expect), None)
    wrong = [s.score for s in ranked if s.id not in q.expect]
    cost = cfg.cost(result.usage.input_tokens, result.usage.output_tokens)
    return Row(
        scorer=name,
        model=result.model or cfg.model,
        q=q.q,
        rank=rank,
        score=by_id.get(best_expected),
        margin=(by_id.get(best_expected, 0.0) - max(wrong)) if wrong else None,
        top=ranked[0].id if ranked else None,
        latency_ms=ms,
        cost_usd=cost,
    )


def summarise(name: str, model: str, rows: list[Row]) -> Summary:
    ok = [r for r in rows if r.error is None]
    n = len(rows)
    lat = sorted(r.latency_ms for r in ok) or [0]
    margins = [r.margin for r in ok if r.margin is not None]
    return Summary(
        scorer=name,
        model=model,
        n=n,
        top1=sum(r.rank == 1 for r in ok) / n if n else 0.0,
        hit3=sum(r.rank is not None and r.rank <= 3 for r in ok) / n if n else 0.0,
        mrr=sum(1 / r.rank for r in ok if r.rank) / n if n else 0.0,
        margin=statistics.mean(margins) if margins else None,
        p50_ms=lat[len(lat) // 2],
        p95_ms=lat[min(len(lat) - 1, int(len(lat) * 0.95))],
        cost_usd=round(sum(r.cost_usd for r in rows), 5),
        failures=n - len(ok),
    )


def markdown(summaries: list[Summary], rows: list[Row], questions: list[Question], cands: int, source: str) -> str:
    out = [
        f"# decide benchmark: {len(questions)} questions, {cands} candidates ({source}), {date.today().isoformat()}",
        "",
    ]
    out.append("| scorer | model | top-1 | hit@3 | MRR | margin | p50 | p95 | cost | failed |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for s in summaries:
        margin = f"{s.margin:+.2f}" if s.margin is not None else "-"
        out.append(
            f"| {s.scorer} | {s.model} | {s.top1:.0%} | {s.hit3:.0%} | {s.mrr:.2f} | {margin} | {s.p50_ms} ms | {s.p95_ms} ms | ${s.cost_usd:.4f} | {s.failures} |"
        )
    out += [
        "",
        "margin: the expected note's score minus the best wrong one, averaged; above zero a threshold can separate them.",
        "",
    ]
    names = [s.scorer for s in summaries]
    out.append("| question | expect | " + " | ".join(names) + " |")
    out.append("|---|---|" + "---|" * len(names))
    for q in questions:
        cells = []
        for name in names:
            r = next((r for r in rows if r.scorer == name and r.q == q.q), None)
            if r is None or r.error:
                cells.append("fail")
            else:
                cells.append(
                    f"#{r.rank} {r.score:.2f}" + (f" ({r.top.split('/')[-1]})" if r.rank != 1 and r.top else "")
                )
        label = q.q + (" *(hard)*" if q.hard else "")
        out.append(f"| {label} | {' / '.join(p.split('/')[-1] for p in q.expect)} | " + " | ".join(cells) + " |")
    out += ["", "cells: rank of the expected note and its score; in brackets what came first when it was not."]
    return "\n".join(out) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--vault", help="a vault directory, indexed in memory")
    src.add_argument("--db", action="store_true", help="the live Postgres index (DATABASE_URL / MEMORY_DATABASE_URL)")
    ap.add_argument("--schema", default="memory")
    ap.add_argument("--questions", required=True, help="YAML: [{q, expect, hard?}]")
    ap.add_argument("--scorer", action="append", default=[], help="NAME=ENDPOINT[=MODEL]; repeatable")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--recent-days", type=int, default=14)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--out", help="write the markdown report here too")
    ap.add_argument("--json", help="write every row as JSON here")
    ap.add_argument(
        "--rows",
        action="append",
        default=[],
        help="render the report from rows saved with --json instead of scoring (repeatable; a later file replaces "
        "a scorer found in an earlier one). --scorer is then not needed.",
    )
    args = ap.parse_args()

    questions = [Question.parse(r) for r in yaml.safe_load(Path(args.questions).read_text())]
    cands = await load_candidates(args, args.today)
    known = {c["id"] for c in cands}
    for q in questions:
        missing = [p for p in q.expect if p not in known]
        if missing:
            print(f"warning: {q.q!r} expects {missing}, not in the catalogue", file=sys.stderr)

    if not args.scorer and not args.rows:
        ap.error("give at least one --scorer, or --rows files to render")
    saved: dict[str, list[Row]] = {}
    for path in args.rows:
        by_scorer: dict[str, list[Row]] = {}
        for raw in json.loads(Path(path).read_text()):
            row = Row.model_validate(raw)
            by_scorer.setdefault(row.scorer, []).append(row)
        saved.update(by_scorer)
    scorers = dict(parse_scorer(s) for s in args.scorer)
    rows: list[Row] = []
    summaries: list[Summary] = []
    for name, mine in saved.items():
        rows += mine
        model = next((r.model for r in mine if r.model), "")
        summaries.append(summarise(name, model, mine))
    for name, (cfg, provider) in scorers.items():
        mine = [await run_one(name, cfg, provider, q, cands, args.timeout) for q in questions]
        rows += mine
        summaries.append(summarise(name, cfg.model, mine))
        s = summaries[-1]
        print(
            f"{name:12s} top-1 {s.top1:.0%}  hit@3 {s.hit3:.0%}  MRR {s.mrr:.2f}  p50 {s.p50_ms} ms  failed {s.failures}",
            file=sys.stderr,
        )
        for r in mine:
            if r.error:
                print(f"    {r.q!r}: {r.error}", file=sys.stderr)

    report = markdown(summaries, rows, questions, len(cands), args.vault or f"db schema {args.schema}")
    print(report)
    if args.out:
        Path(args.out).write_text(report)
    if args.json:
        Path(args.json).write_text(json.dumps([r.model_dump() for r in rows], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
