"""What the model answers through: one forced tool per digest, its schema generated from the pydantic model."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mycelium_sdk import input_schema

from ..schemas import DayDigest, PeriodDigest


class StructuredTool(BaseModel):
    """A tool that exists only to carry a typed answer: the model is forced to call it, we validate the input."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    description: str = Field(min_length=1)
    model: type[BaseModel]

    def spec(self) -> dict[str, Any]:
        """The entry for the request's `tools` list (Anthropic shape; the gateway converts for other vendors)."""
        return {"name": self.name, "description": self.description, "input_schema": input_schema(self.model)}

    def parse(self, raw: dict[str, Any] | None) -> BaseModel:
        return self.model.model_validate(raw or {})


WRITE_DAY = StructuredTool(
    name="write_day",
    description="Write the day: its summary, the facts worth keeping and the notes whose state changed.",
    model=DayDigest,
)

WRITE_PERIOD = StructuredTool(
    name="write_period",
    description="Write the week or month: one summary from its day summaries.",
    model=PeriodDigest,
)
