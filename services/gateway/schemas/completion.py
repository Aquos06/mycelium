"""rpc.llm.complete: the request, what a provider returns, and the reply on the bus.

The request, the result and the reply are the SDK's (mycelium_sdk.llm), the same models every caller sends
and reads; the gateway adds only the stream frame. The wire format is the Anthropic Messages shape:

    messages: [{"role": "user" | "assistant", "content": str | [block, ...]}]
    block:    {"type": "text", "text": ...}
              {"type": "tool_use", "id": ..., "name": ..., "input": {...}}        (assistant)
              {"type": "tool_result", "tool_use_id": ..., "content": str}        (user)
    tools:    [{"name": ..., "description": ..., "input_schema": {...json schema...}}]

Providers that speak something else (OpenAI-compatible) convert both ways in gateway.providers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mycelium_sdk.llm import (
    ChatMessage,
    CompletionReply,
    CompletionRequest,
    CompletionResult,
    ToolCall,
    ToolSpec,
    Usage,
)

__all__ = [
    "ChatMessage",
    "CompletionReply",
    "CompletionRequest",
    "CompletionResult",
    "StreamDelta",
    "ToolCall",
    "ToolSpec",
    "Usage",
]


class StreamDelta(BaseModel):
    """One frame on stream.llm (gateway.stream): a piece of a reply as the model writes it.

    `request` tells one model call from the next within a turn (a planner round that ends in tool calls is
    followed by another call); a reader shows the text of the latest request and drops the earlier one.
    """

    cause: str  # the message being answered: how a reader finds its own stream
    request: str  # this model call
    slot: str
    provider: str
    seq: int = Field(ge=0)
    text: str = ""
    thinking: str = ""  # the model's reasoning before the reply (a reasoning model): shown live, never the reply
    done: bool = False
