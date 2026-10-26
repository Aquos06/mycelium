"""Embeddings for recall's fallback rung (MEMORY.md §4): one vector per note and per summary, through the gateway.

Memory never talks to a model vendor. It asks the gateway's `embed` slot (rpc.llm.embed), which may be TEI on
the GPU box, a vLLM, Ollama or a cloud model (providers.yaml); the slot pins the vector size the index is built
for. The index remembers which model made each vector, so a changed row, or a changed model, is re-embedded by
the next sweep. Sweeps run at start, after each consolidation, every MEMORY_EMBED_EVERY minutes and on
`mctl embed`; each leaves a trace.embed. While the slot is unavailable recall simply has no fuzzy rung.
"""

from __future__ import annotations

import asyncio
import logging
import time

from mycelium_sdk import Bus

from .index import Index
from .schemas import EmbedCall, EmbedSweepReport, EmbedTrace

log = logging.getLogger("mycelium.memory.embed")

PROBE = "mycelium"  # one word, embedded once per process, to learn which model the slot serves


class EmbeddingError(ValueError):
    pass


class Embedder:
    def __init__(
        self,
        bus: Bus,
        index: Index,
        *,
        slot: str = "embed",
        batch: int = 64,
        timeout: float = 60.0,
        min_score: float = 0.45,
    ) -> None:
        self.bus = bus
        self.index = index
        self.slot = slot
        self.batch = batch
        self.timeout = timeout
        self.min_score = min_score  # cosine similarity below which a neighbour is noise
        self.model: str | None = None  # learned from the gateway's first reply
        self.dimensions: int | None = None
        self._lock = asyncio.Lock()  # one sweep at a time; a second caller waits and then finds nothing stale

    # ---- the gateway ---------------------------------------------------------------------------

    async def _embed(self, texts: list[str], cause: str | None) -> tuple[list[list[float]], str, float]:
        call = EmbedCall(slot=self.slot, texts=texts, cause=cause, timeout=self.timeout)
        reply = await self.bus.request("rpc.llm.embed", call.model_dump(mode="json"), timeout=self.timeout + 5)
        if not reply.get("ok"):
            raise EmbeddingError(str(reply.get("error") or "rpc.llm.embed failed"))
        vectors = [list(map(float, v)) for v in reply["vectors"]]
        if len(vectors) != len(texts):
            raise EmbeddingError(f"{len(vectors)} vectors for {len(texts)} texts")
        self.model, self.dimensions = str(reply["model"]), len(vectors[0])
        return vectors, self.model, float(reply.get("cost_usd") or 0.0)

    async def current_model(self, cause: str | None = None) -> str:
        """Which model the slot serves now: needed to know which rows are stale."""
        if self.model is None:
            await self._embed([PROBE], cause)
        assert self.model is not None
        return self.model

    async def embed_query(self, text: str, cause: str | None = None) -> list[float] | None:
        """The question's vector, or None when embeddings are unavailable: recall then skips the rung."""
        try:
            vectors, _model, _cost = await self._embed([text], cause)
        except Exception as e:  # the gateway is down, the slot misconfigured, the vendor slow: degrade, never fail
            log.warning("embed slot unavailable for recall: %s", e)
            return None
        return vectors[0]

    # ---- the sweep ------------------------------------------------------------------------------

    async def sweep(self, cause: str | None = None) -> EmbedSweepReport:
        """Embed every note and summary whose vector is missing or from another model, in batches."""
        t0 = time.monotonic()
        report = EmbedSweepReport()
        async with self._lock:
            try:
                model = report.model = await self.current_model(cause)
                done: set[str] = set()
                while targets := await self.index.stale_embeddings(model, limit=self.batch):
                    if all(t.path in done for t in targets):  # set_embedding is not sticking: never spin
                        raise EmbeddingError(f"{len(targets)} rows stay stale after embedding, e.g. {targets[0].path}")
                    vectors, model_now, cost = await self._embed([t.text for t in targets], cause)
                    if model_now != model:  # the slot changed under us: everything embedded so far is stale again
                        model = report.model = model_now
                        done.clear()
                    for target, vector in zip(targets, vectors, strict=True):
                        await self.index.set_embedding(target.path, vector, model)
                        done.add(target.path)
                    report.embedded += len(targets)
                    report.batches += 1
                    report.cost_usd = round(report.cost_usd + cost, 6)
            except EmbeddingError as e:
                report.error = str(e)
            except Exception as e:
                report.error = f"{type(e).__name__}: {e}"
        report.latency_ms = int((time.monotonic() - t0) * 1000)
        if report.error:
            log.warning("embed sweep failed after %d rows: %s", report.embedded, report.error)
        elif report.embedded:
            log.info("embedded %d rows in %d batches (%s)", report.embedded, report.batches, report.model)
        await self.bus.publish(
            "trace.embed", EmbedTrace(cause=cause, ok=report.error is None, report=report, error=report.error)
        )
        return report
