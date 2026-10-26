"""rpc.llm.decide: a question and candidate texts in, one relevance score per candidate out.

    DecideRequest  {slot: "decide", query, candidates: [{id, text}, ...], cause, hops, timeout}
    DecideResult   what a scorer returns: a score in [0, 1] per candidate id (higher = more about the question),
                   the model, and token usage when the scorer is a chat model
    DecideReply    the reply body (the handler adds ok=true): the result plus who served it and the cost

Two kinds of scorer fit behind one slot: a cross-encoder reranker (TEI's /rerank) and any chat model through
the forced tool `score_candidates`. Memory's decide step
(services/memory/decide/) builds the candidates from its index and loops over hops; the gateway only scores.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .completion import Usage

MAX_CANDIDATES = 256


class Candidate(BaseModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class DecideRequest(BaseModel):
    slot: str = "decide"
    query: str = Field(min_length=1)
    candidates: list[Candidate] = Field(min_length=1, max_length=MAX_CANDIDATES)
    cause: str | None = None  # id of the message this call serves; copied to trace.llm
    hops: int = Field(default=0, ge=0)
    timeout: float | None = Field(default=None, gt=0)  # seconds the caller waits; the gateway gives up first

    @field_validator("candidates")
    @classmethod
    def _unique_ids(cls, v: list[Candidate]) -> list[Candidate]:
        ids = [c.id for c in v]
        if len(set(ids)) != len(ids):
            raise ValueError("candidate ids must be unique")
        return v


class Score(BaseModel):
    id: str
    score: float = Field(ge=0.0, le=1.0)


class ScoreSheet(BaseModel):
    """What a chat model answers through: the forced tool's input."""

    scores: list[Score] = Field(description="one entry per candidate id; 1 = this is what the question is about")


class DecideResult(BaseModel):
    scores: list[Score] = Field(min_length=1)
    model: str
    usage: Usage = Field(default_factory=Usage)  # zeros for a reranker: nothing to bill

    def ranked(self) -> list[Score]:
        return sorted(self.scores, key=lambda s: (-s.score, s.id))


class DecideReply(DecideResult):
    provider: str
    cost_usd: float = Field(default=0.0, ge=0)
    floor: float | None = None  # the scorer's own floor (providers.yaml), for callers that do not set one
