"""The monthly spend counter (KV key `usage/YYYY-MM`) and the rpc.llm.usage reply."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .completion import Usage


class UsageRecord(BaseModel):
    usd: float = Field(default=0.0, ge=0)
    calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    def add(self, cost_usd: float, usage: Usage) -> UsageRecord:
        return UsageRecord(
            usd=round(self.usd + cost_usd, 6),
            calls=self.calls + 1,
            input_tokens=self.input_tokens + usage.input_tokens,
            output_tokens=self.output_tokens + usage.output_tokens,
        )

    def over(self, budget_usd_month: float | None) -> bool:
        return budget_usd_month is not None and self.usd >= budget_usd_month


class UsageReply(UsageRecord):
    """rpc.llm.usage reply body (the handler adds ok=true)."""

    month: str
    budget_usd_month: float | None = None
