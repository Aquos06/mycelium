"""Claude through the Anthropic SDK. The request is already in the Messages shape, so nothing to convert."""

from __future__ import annotations

from typing import Any

from ..schemas import CompletionRequest, CompletionResult, ToolCall, Usage
from .base import ProviderError


def parse_claude_response(resp: Any, model: str) -> CompletionResult:
    """Works on the anthropic SDK's Message object or anything with the same attributes."""
    text: list[str] = []
    calls: list[ToolCall] = []
    for block in getattr(resp, "content", None) or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            text.append(getattr(block, "text", "") or "")
        elif kind == "tool_use":
            calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input or {})))
    usage = getattr(resp, "usage", None)
    return CompletionResult(
        text="".join(text),
        tool_calls=calls,
        stop_reason=getattr(resp, "stop_reason", None) or ("tool_use" if calls else "end_turn"),
        model=getattr(resp, "model", None) or model,
        usage=Usage(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        ),
    )


class ClaudeProvider:
    def __init__(
        self,
        name: str,
        model: str,
        api_key: str | None,
        max_tokens: int = 1024,
        client: Any = None,
        base_url: str | None = None,  # only to go through a proxy; the SDK knows the real endpoint
    ):
        self.name = name
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.base_url = base_url
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            if not self.api_key:
                raise ProviderError(f"provider {self.name!r} has no API key")
            from anthropic import AsyncAnthropic  # lazy: tests never need the SDK

            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = AsyncAnthropic(**kwargs)
        return self._client

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": req.max_tokens or self.max_tokens,
            "messages": req.messages,
        }
        if req.system:
            kwargs["system"] = req.system
        if req.tools:
            kwargs["tools"] = req.tools
        if req.tool_choice:
            kwargs["tool_choice"] = {"type": "tool", "name": req.tool_choice}
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        try:
            resp = await client.messages.create(**kwargs)
        except Exception as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}: {e}") from e
        return parse_claude_response(resp, self.model)
