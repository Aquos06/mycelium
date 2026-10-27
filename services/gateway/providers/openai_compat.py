"""Anything with /v1/chat/completions: the generic provider every OpenAI-shaped vendor builds on.

Converts the Anthropic-shaped request to the OpenAI shape and the response back:

    system                      -> a leading {"role": "system"} message
    assistant tool_use blocks   -> message.tool_calls [{type: function, function: {name, arguments: json}}]
    user tool_result blocks     -> {"role": "tool", "tool_call_id", "content"}
    tools[].input_schema        -> tools[].function.parameters
    finish_reason               -> stop_reason (stop/tool_calls/length -> end_turn/tool_use/max_tokens)

Vendor classes (openai.py, ollama.py, vllm.py) override the little that differs; cloud vendors
without quirks (groq, deepseek, mistral, ...) use this class directly with their kind's defaults.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from ..schemas import CompletionRequest, CompletionResult, ToolCall, Usage
from .base import ProviderError, StreamSink

_FINISH = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role, content = m["role"], m["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})},
                }
                for b in content
                if b.get("type") == "tool_use"
            ]
            msg: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            for b in content:
                if b.get("type") == "tool_result":
                    c = b.get("content")
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": b["tool_use_id"],
                            "content": c if isinstance(c, str) else json.dumps(c, default=str),
                        }
                    )
                elif b.get("type") == "text":
                    out.append({"role": "user", "content": b.get("text", "")})
    return out


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def parse_openai_response(data: Mapping[str, Any], model: str) -> CompletionResult:
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError("no choices in response")
    msg = choices[0].get("message") or {}
    calls: list[ToolCall] = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            args = {"_raw": raw}
        calls.append(ToolCall(id=str(tc.get("id") or f"call_{len(calls)}"), name=fn.get("name", ""), input=args))
    usage = data.get("usage") or {}
    finish = choices[0].get("finish_reason")
    return CompletionResult(
        text=msg.get("content") or "",
        tool_calls=calls,
        # tool calls win: some servers (Ollama) report finish_reason=stop while returning tool calls
        stop_reason="tool_use" if calls else _FINISH.get(finish, "end_turn"),
        model=str(data.get("model") or model),
        usage=Usage(
            input_tokens=int(usage.get("prompt_tokens") or 0), output_tokens=int(usage.get("completion_tokens") or 0)
        ),
    )


async def collect_sse(lines: AsyncIterator[str], sink: StreamSink) -> dict[str, Any]:
    """A `stream: true` response, reassembled into the shape parse_openai_response reads.

    Content deltas go to `sink.on_text` as they arrive and are joined; reasoning deltas go to `sink.on_thinking`
    and nowhere else (vLLM with a reasoning parser and DeepSeek name them `reasoning_content`, newer vLLM,
    Ollama and OpenRouter `reasoning`); tool-call deltas are keyed by `index` and
    their `arguments` fragments concatenated (that is how every OpenAI-shaped server streams a call); the
    last chunk carries `usage` when `stream_options.include_usage` was honoured, and finish_reason comes on
    the last chunk of the choice.
    """
    content: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    finish: str | None = None
    usage: dict[str, Any] = {}
    model: str | None = None
    async for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            if payload == "[DONE]":
                break
            continue
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue  # a keep-alive or a partial line: nothing to read
        model = chunk.get("model") or model
        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            thought = delta.get("reasoning_content") or delta.get("reasoning")
            if thought and isinstance(thought, str):
                await sink.on_thinking(thought)
            piece = delta.get("content")
            if piece:
                content.append(piece)
                await sink.on_text(piece)
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(
                    int(tc.get("index") or 0), {"id": None, "function": {"name": "", "arguments": ""}}
                )
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    tool_calls = [calls[i] for i in sorted(calls)]
    return {
        "model": model,
        "usage": usage,
        "choices": [
            {
                "finish_reason": finish,
                "message": {"content": "".join(content) or None, "tool_calls": tool_calls or None},
            }
        ],
    }


class OpenAICompatProvider:
    max_tokens_field = "max_tokens"  # OpenAI itself moved on to max_completion_tokens (openai.py)

    def __init__(
        self,
        name: str,
        model: str,
        endpoint: str,
        api_key: str | None = None,
        max_tokens: int = 1024,
        http: Any = None,
        timeout: float = 120.0,
        require_key: bool = False,
        headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ):
        self.name = name
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.require_key = require_key
        self.headers = dict(headers or {})
        self.extra_body = dict(extra_body or {})
        self._http = http

    def _get_http(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    def body(self, req: CompletionRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(req.system, req.messages),
            self.max_tokens_field: req.max_tokens or self.max_tokens,
        }
        if req.tools:
            body["tools"] = to_openai_tools(req.tools)
        if req.tool_choice:
            body["tool_choice"] = {"type": "function", "function": {"name": req.tool_choice}}
        if req.temperature is not None:
            body["temperature"] = req.temperature
        body.update(self.extra_body)
        return body

    async def complete(self, req: CompletionRequest, sink: StreamSink | None = None) -> CompletionResult:
        if self.require_key and not self.api_key:
            raise ProviderError(f"provider {self.name!r} has no API key")
        headers = dict(self.headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.endpoint}/chat/completions"
        timeout = req.timeout or self.timeout  # the caller's budget, not a fixed client default
        try:
            if sink is None:
                r = await self._get_http().post(url, json=self.body(req), headers=headers, timeout=timeout)
                r.raise_for_status()
                data = r.json()
            else:
                body = {**self.body(req), "stream": True, "stream_options": {"include_usage": True}}
                async with self._get_http().stream("POST", url, json=body, headers=headers, timeout=timeout) as r:
                    r.raise_for_status()
                    data = await collect_sse(r.aiter_lines(), sink)
        except Exception as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}: {e}") from e
        return parse_openai_response(data, self.model)
