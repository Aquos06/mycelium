"""A week or month from its day summaries, which periods a day closes, and which recent periods are missing."""

from __future__ import annotations

import time
from datetime import date, timedelta

from mycelium_sdk import Bus

from ..index import Index
from ..indexer import index_file
from ..schemas import PeriodDigest, RollupReport, period_days, period_path, periods_closed_by
from ..vault import Vault
from .errors import ConsolidationError
from .linking import autolink
from .model import ModelCaller
from .prompts import period_prompt
from .tools import WRITE_PERIOD
from .traces import trace_rollup


class Rollups:
    def __init__(self, bus: Bus, vault: Vault, index: Index, caller: ModelCaller) -> None:
        self.bus = bus
        self.vault = vault
        self.index = index
        self.caller = caller

    due = staticmethod(periods_closed_by)

    async def missing(self, today: date, days: int = 7) -> list[tuple[str, str]]:
        """Periods closed in the last `days` days that have no summary: a failed or skipped rollup to retry."""
        out: list[tuple[str, str]] = []
        for back in range(days, 0, -1):
            for period, key in periods_closed_by(today - timedelta(days=back)):
                if await self.index.summary(period, key) is None:
                    out.append((period, key))
        return out

    async def run(
        self, period: str, key: str, cause: str | None = None, *, only_if_missing: bool = False
    ) -> RollupReport:
        """Write one period from its day summaries. Traced on trace.rollup either way; a failure also raises.

        `only_if_missing` leaves an existing summary alone: an eventless Sunday replayed by catch-up must not
        pay for and rewrite the week every time."""
        t0 = time.monotonic()
        report = RollupReport(period=period, key=key)
        try:
            days = period_days(period, key)
            if only_if_missing and await self.index.summary(period, key) is not None:
                report.skipped, report.reason = True, "already written"
            else:
                summaries = await self.index.summaries_in("day", [d.isoformat() for d in days])
                report.sources = len(summaries)
                if not summaries:
                    report.skipped, report.reason = True, "no day summaries"
                else:
                    digest = await self.caller.ask(
                        period_prompt(period, key, days, summaries), WRITE_PERIOD, cause, report
                    )
                    assert isinstance(digest, PeriodDigest)
                    path = period_path(period, key)
                    self.vault.write_text(path, autolink(digest.summary, await self.index.vocabulary()))
                    await index_file(self.vault, self.index, path)
                    report.summary_path = path
        except ConsolidationError as e:
            report.error, report.latency_ms = str(e), _ms(t0)
            await trace_rollup(self.bus, report, ok=False, cause=cause, error=str(e))
            raise
        except Exception as e:
            report.error, report.latency_ms = f"{type(e).__name__}: {e}", _ms(t0)
            await trace_rollup(self.bus, report, ok=False, cause=cause, error=report.error)
            raise ConsolidationError(report.error) from e
        report.latency_ms = _ms(t0)
        await trace_rollup(self.bus, report, ok=True, cause=cause)
        return report


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)
