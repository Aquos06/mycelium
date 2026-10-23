"""rpc.llm.complete: the request, what a provider returns, and the reply on the bus.

The wire format is the Anthropic Messages shape, because it is the richer one:

    messages: [{"role": "user" | "assistant", "content": str | [block, ...]}]
    block:    {"type": "text", "text": ...}
              {"type": "tool_use", "id": ..., "name": ..., "input": {...}}        (assistant)
              {"type": "tool_result", "tool_use_id": ..., "content": str}        (user)
    tools:    [{"name": ..., "description": ..., "input_schema": {...json schema...}}]

Providers that speak something else (OpenAI-compatible) convert both ways in gateway.providers.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

ROLES = ("user", "assistant")


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class CompletionRequest(BaseModel):
    slot: str = "planner"
    system: str = ""
    messages: list[dict[str, Any]] = Field(min_length=1)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    cause: str | None = None  # id of the message this call serves; copied to trace.llm
    hops: int = Field(default=0, ge=0)  # that message's hops; trace.llm is one step further down
    timeout: float | None = Field(default=None, gt=0)  # seconds the caller waits; the gateway gives up first

    @field_validator("messages")
    @classmethod
    def _roles(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for i, m in enumerate(v):
            if m.get("role") not in ROLES:
                raise ValueError(f"messages[{i}].role must be one of {ROLES}")
            if "content" not in m:
                raise ValueError(f"messages[{i}] has no content")
        return v

    @field_validator("tools")
    @classmethod
    def _tools(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for i, t in enumerate(v):
            if not t.get("name") or not isinstance(t.get("input_schema"), dict):
                raise ValueError(f"tools[{i}] needs a name and an input_schema")
        return v


class CompletionResult(BaseModel):
    """What a provider returns, vendor differences already smoothed out."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str = "end_turn"  # end_turn | tool_use | max_tokens
    model: str
    usage: Usage = Field(default_factory=Usage)


class CompletionReply(CompletionResult):
    """The rpc.llm.complete reply body (the handler adds ok=true): the result, who served it, what it cost."""

    provider: str
    cost_usd: float = Field(default=0.0, ge=0)
