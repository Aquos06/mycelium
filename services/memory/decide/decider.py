"""The loop: score the catalogue, keep what clears the floor, hop, score again. A few rounds, a note budget, one trace."""

from __future__ import annotations

import logging
import time
from datetime import date

from mycelium_sdk import Bus

from ..embedder import Embedder
from ..index import Index
from ..schemas import DecideCall, DecideCandidate, DecideReport, DecideTrace, Pick
from .catalogue import catalogue
from .expand import expansion

log = logging.getLogger("mycelium.memory.decide")

CHUNK = 256  # the gateway's MAX_CANDIDATES per call
DEFAULT_FLOOR = 0.5  # when neither memory nor the scorer names one


class DecideError(ValueError):
    pass


def scored_text(c: DecideCandidate) -> str:
    """What the scorer reads: a hop candidate carries the link that led to it, so the connection counts."""
    return c.text if c.via == "catalogue" else f"{c.via}: {c.text}"


class Decider:
    def __init__(
        self,
        bus: Bus,
        index: Index,
        *,
        slot: str = "decide",
        floor: float | None = None,
        rounds: int = 2,
        timeout: float = 30.0,
        max_candidates: int = 200,
        recent_days: int = 14,
        embedder: Embedder | None = None,
    ) -> None:
        self.bus = bus
        self.index = index
        self.slot = slot
        self.floor = floor  # under this a candidate is not about the question; None: the scorer's own (providers.yaml)
        self.rounds = rounds
        self.timeout = timeout
        self.max_candidates = max_candidates  # above this the catalogue is shrunk to the embedding neighbours
        self.recent_days = recent_days
        self.embedder = embedder

    async def _score(
        self, query: str, cands: list[DecideCandidate], cause: str | None, report: DecideReport
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        cands = list({c.id: c for c in cands}.values())  # the gateway refuses a repeated id; the first mention stands
        for i in range(0, len(cands), CHUNK):
            chunk = cands[i : i + CHUNK]
            call = DecideCall(
                slot=self.slot,
                query=query,
                candidates=[{"id": c.id, "text": scored_text(c)} for c in chunk],
                cause=cause,
                timeout=self.timeout,
            )
            reply = await self.bus.request("rpc.llm.decide", call.model_dump(mode="json"), timeout=self.timeout + 5)
            if not reply.get("ok"):
                raise DecideError(str(reply.get("error") or "rpc.llm.decide failed"))
            report.calls += 1
            report.scored += len(chunk)
            report.model = str(reply.get("model") or report.model or "")
            report.provider = str(reply.get("provider") or report.provider or "")
            if report.floor is None:
                report.floor = self.floor if self.floor is not None else reply.get("floor")
            report.cost_usd = round(report.cost_usd + float(reply.get("cost_usd") or 0.0), 6)
            scores.update({s["id"]: float(s["score"]) for s in reply["scores"]})
        return scores

    async def _first_round(
        self, query: str, today: date, exclude: set[str], cause: str | None
    ) -> list[DecideCandidate]:
        cands = [c for c in await catalogue(self.index, today, self.recent_days) if c.path not in exclude]
        if len(cands) <= self.max_candidates:
            return cands
        if self.embedder is not None and (vector := await self.embedder.embed_query(query, cause)) is not None:
            near = {n.record.path for n in await self.index.nearest(vector, limit=self.max_candidates)}
            kept = [c for c in cands if c.path in near]
            if kept:
                return kept
        log.warning("catalogue has %d rows, scoring the first %d", len(cands), self.max_candidates)
        return cands[: self.max_candidates]

    async def decide(
        self,
        query: str,
        today: date,
        *,
        exclude: set[str] | None = None,
        seeds: list[str] | None = None,
        budget: int = 8,
        cause: str | None = None,
    ) -> DecideReport:
        """Picks above the floor, best first within each round, within `budget`; a failure ends the loop and is traced,
        what was picked before it stays. `exclude`: paths recall already opened. `seeds`: the notes the exact rungs
        opened; given, round one scores what they link to, what links to them and their facts instead of the
        catalogue, so the scorer picks the hops for a named or dated question too."""
        t0 = time.monotonic()
        report = DecideReport(seeds=len(seeds or ()))
        picked: set[str] = set(exclude or ()) | set(seeds or ())
        proposed: set[tuple[str, str]] = set()
        try:
            if seeds:
                starts = [Pick(id=p, path=p, score=1.0, round=1, via="seed") for p in seeds]
                cands = await expansion(self.index, starts, picked)
            else:
                cands = await self._first_round(query, today, picked, cause)
            proposed.update((c.id, c.via) for c in cands)
            for rnd in range(1, self.rounds + 1):
                if not cands or len(report.picked) >= budget:
                    break
                report.rounds = rnd
                scores = await self._score(query, cands, cause, report)
                floor = report.floor if report.floor is not None else DEFAULT_FLOOR
                report.floor = floor
                new = sorted(
                    (c for c in cands if c.id not in picked and scores.get(c.id, 0.0) >= floor),
                    key=lambda c: (-scores[c.id], c.id),
                )[: budget - len(report.picked)]
                if not new:
                    break
                picks = [
                    Pick(id=c.id, path=c.path, score=round(scores[c.id], 4), round=rnd, via=c.via, excerpt=c.excerpt)
                    for c in new
                ]
                report.picked.extend(picks)
                picked.update(p.id for p in picks)
                ids = {i for i, _ in proposed}
                cands = [
                    c
                    for c in await expansion(self.index, picks, picked)
                    if (c.id, c.via) not in proposed and (c.excerpt is None or c.id not in ids)
                ]
                proposed.update((c.id, c.via) for c in cands)
        except DecideError as e:
            report.error = str(e)
        except Exception as e:
            report.error = f"{type(e).__name__}: {e}"
        report.latency_ms = int((time.monotonic() - t0) * 1000)
        if report.error:
            log.warning("decide failed after %d picks: %s", len(report.picked), report.error)
        await self.bus.publish(
            "trace.decide",
            DecideTrace(cause=cause, query=query, ok=report.error is None, report=report, error=report.error),
        )
        return report
