"""What the model answers through: one forced tool per digest (the SDK's Tool), its schema generated from the
pydantic model."""

from __future__ import annotations

from mycelium_sdk import Tool

from ..schemas import DayDigest, PeriodDigest

WRITE_DAY = Tool(
    name="write_day",
    description="Write the day: its summary, the facts worth keeping and the notes whose state changed.",
    args=DayDigest,
)

WRITE_PERIOD = Tool(
    name="write_period",
    description="Write the week or month: one summary from its day summaries.",
    args=PeriodDigest,
)
