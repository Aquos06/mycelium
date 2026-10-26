"""Embeddings over the OpenAI shape: POST {endpoint}/embeddings with {"model", "input": [...]}.

TEI (`/v1/embeddings`), vLLM (`--task embed`), Ollama and OpenAI itself all speak it; Gemini and
Mistral too through their OpenAI-compatible endpoints. `request_dimensions` asks the vendor for the
slot's size, which OpenAI's text-embedding-3 models honour; other vendors return their native size and
the gateway checks it against the slot.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..schemas import EmbedRequest, EmbedResult, Usage
from .base import ProviderError


def parse_embeddings_response(data: Mapping[str, Any], model: str) -> EmbedResult:
    items = data.get("data") or []
    if not items:
        raise ProviderError("no embeddings in response")
    vectors = [list(map(float, item["embedding"])) for item in sorted(items, key=lambda i: i.get("index", 0))]
    usage = data.get("usage") or {}
    return EmbedResult(
        vectors=vectors,
        model=str(data.get("model") or model),
        dimensions=len(vectors[0]),
        usage=Usage(input_tokens=int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)),
    )


class OpenAIEmbeddingsProvider:
    def __init__(
        self,
        name: str,
        model: str,
        endpoint: str,
        api_key: str | None = None,
        http: Any = None,
        timeout: float = 60.0,
        require_key: bool = False,
        headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        request_dimensions: int | None = None,
    ):
        self.name = name
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.require_key = require_key
        self.headers = dict(headers or {})
        self.extra_body = dict(extra_body or {})
        self.request_dimensions = request_dimensions
        self._http = http

    def _get_http(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    def body(self, req: EmbedRequest) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "input": req.texts}
        if self.request_dimensions:
            body["dimensions"] = self.request_dimensions
        body.update(self.extra_body)
        return body

    async def embed(self, req: EmbedRequest) -> EmbedResult:
        if self.require_key and not self.api_key:
            raise ProviderError(f"provider {self.name!r} has no API key")
        headers = dict(self.headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            r = await self._get_http().post(
                f"{self.endpoint}/embeddings", json=self.body(req), headers=headers, timeout=req.timeout or self.timeout
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}: {e}") from e
        return parse_embeddings_response(data, self.model)
