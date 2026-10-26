"""rpc.llm.embed: texts in, one vector per text out.

    EmbedRequest  {slot: "embed", texts: [...], cause, hops, timeout}
    EmbedResult   what a provider returns: vectors, model, dimensions, usage (input tokens only)
    EmbedReply    the reply body (the handler adds ok=true): the result plus who served it and the cost

Every vendor that embeds speaks the OpenAI shape (/v1/embeddings), TEI, vLLM and Ollama included, so
one provider covers them; the slot's `dimensions` pins the vector size the index was built for.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from .completion import Usage

MAX_TEXTS = 256


class EmbedRequest(BaseModel):
    slot: str = "embed"
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)
    cause: str | None = None  # id of the message this call serves; copied to trace.llm
    hops: int = Field(default=0, ge=0)
    timeout: float | None = Field(default=None, gt=0)  # seconds the caller waits; the gateway gives up first

    @field_validator("texts")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        if any(not t.strip() for t in v):
            raise ValueError("every text must be non-empty")
        return v


class EmbedResult(BaseModel):
    vectors: list[list[float]] = Field(min_length=1)
    model: str
    dimensions: int = Field(ge=1)
    usage: Usage = Field(default_factory=Usage)

    @model_validator(mode="after")
    def _same_size(self) -> EmbedResult:
        if any(len(v) != self.dimensions for v in self.vectors):
            raise ValueError("every vector must have `dimensions` entries")
        return self


class EmbedReply(EmbedResult):
    provider: str
    cost_usd: float = Field(default=0.0, ge=0)
