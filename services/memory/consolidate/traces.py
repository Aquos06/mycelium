"""Every run leaves a trace, failed ones included: trace.consolidate for a day, trace.rollup for a period."""

from __future__ import annotations

from mycelium_sdk import Bus

from ..schemas import ConsolidateTrace, ConsolidationReport, RollupReport, RollupTrace


async def trace_day(
    bus: Bus, report: ConsolidationReport, *, ok: bool, cause: str | None, error: str | None = None
) -> None:
    await bus.publish(
        "trace.consolidate", ConsolidateTrace(cause=cause, hops=1 if cause else 0, ok=ok, report=report, error=error)
    )


async def trace_rollup(
    bus: Bus, report: RollupReport, *, ok: bool, cause: str | None, error: str | None = None
) -> None:
    await bus.publish(
        "trace.rollup", RollupTrace(cause=cause, hops=1 if cause else 0, ok=ok, report=report, error=error)
    )
