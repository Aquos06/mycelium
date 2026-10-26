"""Providers: one `complete()` call, several vendors behind it.

base.py           the Provider protocol and ProviderError
claude.py         the Anthropic SDK; the wire shape is native
openai_compat.py  the generic /v1/chat/completions client; converts the wire shape both ways
openai.py         OpenAI itself (max_completion_tokens)
embeddings.py     the one embeddings provider: /v1/embeddings for TEI, vLLM, Ollama, OpenAI, ...
ollama.py         Ollama next to the gateway (no key, long first-load timeout)
vllm.py           vLLM on the GPU box (no key, tool parser flags on the server)

Cloud vendors without quirks (openrouter, groq, deepseek, mistral, gemini, xai) use the generic
class with their kind's defaults (schemas/kinds.py). `build_provider` turns a ProviderConfig into
the right one and reads its key from the environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from ..schemas import ProviderConfig
from .base import EmbeddingProvider, Provider, ProviderError
from .claude import ClaudeProvider
from .embeddings import OpenAIEmbeddingsProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .openai_compat import OpenAICompatProvider
from .vllm import VLLMProvider

__all__ = [
    "Provider",
    "ProviderError",
    "ClaudeProvider",
    "EmbeddingProvider",
    "OpenAIEmbeddingsProvider",
    "OpenAICompatProvider",
    "OpenAIProvider",
    "OllamaProvider",
    "VLLMProvider",
    "PROVIDER_CLASSES",
    "build_provider",
]

# kinds with a class of their own; every other openai-protocol kind is the generic client
PROVIDER_CLASSES: dict[str, type[OpenAICompatProvider]] = {
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
    "vllm": VLLMProvider,
}


def build_provider(
    name: str, cfg: ProviderConfig, env: Mapping[str, str] | None = None, task: str = "complete"
) -> Provider | EmbeddingProvider:
    env = os.environ if env is None else env
    key = env.get(cfg.key_env) if cfg.key_env else None
    if task == "embed":
        if cfg.protocol != "openai":
            raise ValueError(f"{cfg.kind} cannot embed")
        return OpenAIEmbeddingsProvider(
            name,
            cfg.model,
            endpoint=cfg.endpoint or "",
            api_key=key,
            require_key=cfg.info.needs_key,
            headers=cfg.headers,
            extra_body=cfg.extra_body,
            request_dimensions=cfg.dimensions if cfg.kind == "openai" else None,  # only OpenAI honours it
        )
    if cfg.protocol == "anthropic":
        return ClaudeProvider(name, cfg.model, api_key=key, max_tokens=cfg.max_tokens, base_url=cfg.endpoint)
    cls = PROVIDER_CLASSES.get(cfg.kind, OpenAICompatProvider)
    return cls(
        name,
        cfg.model,
        endpoint=cfg.endpoint or "",
        api_key=key,
        max_tokens=cfg.max_tokens,
        require_key=cfg.info.needs_key,
        headers=cfg.headers,
        extra_body=cfg.extra_body,
    )
