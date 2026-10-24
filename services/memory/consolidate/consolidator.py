"""The facade: run(day) and rollup(period, key). Owns the parts and the day's tracing; the parts own the work."""

from __future__ import annotations

import logging
import time
from datetime import date

from mycelium_sdk import Bus

from ..events import EventSource
from ..index import Index
from ..schemas import ConsolidationReport, DayDigest, RollupReport
from ..vault import Vault
from .errors import ConsolidationError
from .model import ModelCaller
from .prompts import day_prompt
from .rollups import Rollups
from .tools import WRITE_DAY
from .traces import trace_day
from .writer import DigestWriter

log = logging.getLogger("mycelium.memory.consolidate")


class Consolidator:
    def __init__(
        self,
        bus: Bus,
        vault: Vault,
        index: Index,
        events: EventSource,
        tz: str,
        slot: str = "consolidate",
        timeout: float = 180.0,
        max_tokens: int | None = None,  # None: the provider's own max_tokens from providers.yaml decides
        max_event_chars: int = 24_000,
        max_rounds: int = 2,
    ) -> None:
        self.bus = bus
        self.vault = vault
        self.index = index
        self.events = events
        self.tz = tz
        self.max_event_chars = max_event_chars
        self.caller = ModelCaller(bus, slot=slot, timeout=timeout, max_tokens=max_tokens, max_rounds=max_rounds)
        self.writer = DigestWriter(vault, index)
        self.rollups = Rollups(bus, vault, index, self.caller)

    # the model settings live on the caller; these keep the one-object view for callers and tests
    @property
    def timeout(self) -> float:
        return self.caller.timeout

    @property
    def max_tokens(self) -> int | None:
        return self.caller.max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int | None) -> None:
        self.caller.max_tokens = value

    async def run(self, day: date, cause: str | None = None) -> ConsolidationReport:
        """One day, then the week or month it closes. Every outcome is traced; a failure also raises.

        latency_ms is the day's own; each rollup carries its own. A rollup that fails is recorded on the
        report with its error and never fails the day."""
        t0 = time.monotonic()
        report = ConsolidationReport(day=day)
        try:
            events = await self.events.for_day(day, self.tz)
            report.events = len(events)
            if not events:
                report.skipped, report.reason = True, "no events"
            else:
                prompt = day_prompt(
                    day, self.tz, self.vault.notes(), await self.index.facts(day=day), events, self.max_event_chars
                )
                digest = await self.caller.ask(prompt, WRITE_DAY, cause, report)
                assert isinstance(digest, DayDigest)
                await self.writer.apply(day, digest, events, report)
            report.latency_ms = _ms(t0)
            report.rollups = await self._rollups_due(day, cause, only_if_missing=report.skipped)
        except ConsolidationError as e:
            report.latency_ms = _ms(t0)
            await trace_day(self.bus, report, ok=False, cause=cause, error=str(e))
            raise
        except Exception as e:  # reading events, writing the vault, indexing: a paid digest must not vanish silently
            report.latency_ms = _ms(t0)
            await trace_day(self.bus, report, ok=False, cause=cause, error=f"{type(e).__name__}: {e}")
            raise ConsolidationError(f"{type(e).__name__}: {e}") from e
        await trace_day(self.bus, report, ok=True, cause=cause)
        return report

    async def rollup(self, period: str, key: str, cause: str | None = None) -> RollupReport:
        return await self.rollups.run(period, key, cause)

    async def _rollups_due(self, day: date, cause: str | None, *, only_if_missing: bool) -> list[RollupReport]:
        """The periods this day closes. An eventless day (a catch-up replay) rewrites nothing that exists."""
        out: list[RollupReport] = []
        for period, key in Rollups.due(day):
            try:
                out.append(await self.rollups.run(period, key, cause, only_if_missing=only_if_missing))
            except ConsolidationError as e:  # traced by Rollups.run; kept on the day's report so nobody misses it
                log.warning("%s rollup %s failed: %s", period, key, e)
                out.append(RollupReport(period=period, key=key, error=str(e)))  # type: ignore[arg-type]
        return out


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)
