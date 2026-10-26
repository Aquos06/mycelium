"""Embeddings (MEMORY.md §4, the fallback rung): what memory embeds, what it sends, what it reports."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mycelium_sdk import Envelope

from .index import NoteRecord, SummaryRecord


class EmbedTarget(BaseModel):
    """One row that needs a vector: what to embed and where to store it."""

    path: str
    text: str


class Neighbour(BaseModel):
    """A note or summary near a question, with its cosine similarity (1 = identical)."""

    record: NoteRecord | SummaryRecord
    score: float


class EmbedCall(BaseModel):
    """rpc.llm.embed as memory fills it (the gateway validates it again as EmbedRequest)."""

    slot: str = "embed"
    texts: list[str] = Field(min_length=1)
    cause: str | None = None
    timeout: float = Field(gt=0)


class EmbedSweepReport(BaseModel):
    """One sweep: every stale row embedded in batches; also the rpc.memory.embed reply."""

    model: str | None = None
    embedded: int = 0
    batches: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None  # set when the sweep stopped early; what was embedded before it stays


class EmbedTrace(Envelope):
    """trace.embed: one per sweep."""

    source: str = "memory"
    ok: bool
    report: EmbedSweepReport
    error: str | None = None


def embedding_text(record: NoteRecord | SummaryRecord) -> str:
    """What stands for a row in vector space: a note by its name, aliases and current state; a summary by its text."""
    if isinstance(record, NoteRecord):
        aliases = f" ({', '.join(a for a in record.aliases if a != record.name)})" if record.aliases else ""
        head = f"{record.name}{aliases}, {record.type}"
        return f"{head}. {record.summary}" if record.summary else head
    return f"{record.period} {record.key}: {record.text}"


Kind = Literal["note", "summary"]
