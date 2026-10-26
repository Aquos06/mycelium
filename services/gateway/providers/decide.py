"""Scorers for rpc.llm.decide: a question and candidates in, a score in [0, 1] per candidate out.

TeiRerankProvider   a cross-encoder reranker behind TEI (POST /rerank): one forward pass over all pairs
ToolDecideProvider  any chat model: the candidates in the prompt, the answer through the forced tool
                    `score_candidates`, billed by tokens like every completion
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mycelium_sdk import input_schema

from ..schemas import CompletionRequest, DecideRequest, DecideResult, Score, ScoreSheet
from .base import Provider, ProviderError


def _clamp(x: Any) -> float:
    try:
        return min(1.0, max(0.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _http(client: Any, timeout: float) -> Any:
    if client is None:
        import httpx

        client = httpx.AsyncClient(timeout=timeout)
    return client


# ---- TEI reranker ------------------------------------------------------------------------------------


class TeiRerankProvider:
    """TEI serving a reranker (BAAI/bge-reranker-v2-m3): POST {root}/rerank {query, texts} -> [{index, score}]."""

    def __init__(
        self,
        name: str,
        model: str,
        endpoint: str,
        http: Any = None,
        timeout: float = 60.0,
        headers: Mapping[str, str] | None = None,
        api_key: str | None = None,
    ):
        self.name = name
        self.model = model
        self.root = endpoint.rstrip("/").removesuffix("/v1")  # the tei kind's default endpoint ends in /v1
        self.timeout = timeout
        self.headers = dict(headers or {})
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self._http = http

    async def decide(self, req: DecideRequest) -> DecideResult:
        body = {"query": req.query, "texts": [c.text for c in req.candidates], "raw_scores": False, "truncate": True}
        try:
            r = await _http(self._http, self.timeout).post(
                f"{self.root}/rerank", json=body, headers=self.headers, timeout=req.timeout or self.timeout
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}: {e}") from e
        self._http = self._http or None
        if not isinstance(data, list):
            raise ProviderError(f"{self.name}: unexpected rerank response")
        by_index = {int(item["index"]): _clamp(item.get("score")) for item in data}
        scores = [Score(id=c.id, score=by_index.get(i, 0.0)) for i, c in enumerate(req.candidates)]
        return DecideResult(scores=scores, model=self.model)


# ---- any chat model, through a forced tool -------------------------------------------------------------

SCORE_TOOL = {
    "name": "score_candidates",
    "description": "Score every candidate: how much it is what the question is about.",
    "input_schema": input_schema(ScoreSheet),
}
SYSTEM = (
    "You judge which notes from someone's personal memory a question is about. Each candidate is one note: "
    "its name, aliases and type, then its current state; or a day, week or month summary. Give every candidate a "
    "score from 0 to 1: 1 when the note is exactly what the question asks about, around 0.5 when it is related "
    "and would help answer, 0 when unrelated. Notes may be in another language than the question. Score by "
    "meaning, not by shared words. Use the score_candidates tool and nothing else."
)


def decide_prompt(req: DecideRequest) -> str:
    lines = [f"Question: {req.query}", "", "Candidates:"]
    lines += [f"- id: {c.id}\n  {c.text}" for c in req.candidates]
    return "\n".join(lines)


class ToolDecideProvider:
    def __init__(self, name: str, inner: Provider, model: str):
        self.name = name
        self.inner = inner
        self.model = model

    async def decide(self, req: DecideRequest) -> DecideResult:
        call = CompletionRequest(
            slot=req.slot,
            system=SYSTEM,
            messages=[{"role": "user", "content": decide_prompt(req)}],
            tools=[SCORE_TOOL],
            tool_choice=SCORE_TOOL["name"],
            cause=req.cause,
            hops=req.hops,
            timeout=req.timeout,
            temperature=0.0,
        )
        try:
            result = await self.inner.complete(call)
        except ProviderError as e:
            if "tool_choice" not in str(e):
                raise
            result = await self.inner.complete(call.model_copy(update={"tool_choice": None}))  # ask unforced
        sheet = next((c for c in result.tool_calls if c.name == SCORE_TOOL["name"]), None)
        if sheet is None:
            raise ProviderError(f"{self.name}: the model did not call {SCORE_TOOL['name']}")
        try:
            parsed = ScoreSheet.model_validate(sheet.input)
        except ValueError as e:
            raise ProviderError(f"{self.name}: bad score sheet: {e}") from e
        given = {s.id: s.score for s in parsed.scores}
        scores = [Score(id=c.id, score=given.get(c.id, 0.0)) for c in req.candidates]  # unscored = 0
        return DecideResult(scores=scores, model=result.model, usage=result.usage)
