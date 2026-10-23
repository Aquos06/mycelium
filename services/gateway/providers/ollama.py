"""Ollama next to the gateway (`docker compose --profile local up -d ollama`). Speaks the OpenAI shape on /v1.

- No key. Models are `name:tag` (qwen2.5:14b) and must be pulled first (`make local MODEL=qwen2.5:14b`).
- The default context window is small; the compose service sets OLLAMA_CONTEXT_LENGTH (16384).
- Tool calling works for models whose template supports it (qwen2.5, qwen3, llama3.1+, mistral-nemo).
- The first call after idle loads the model into memory, hence the long timeout.
"""

from __future__ import annotations

from .openai_compat import OpenAICompatProvider


class OllamaProvider(OpenAICompatProvider):
    def __init__(self, *args, timeout: float = 300.0, **kwargs):
        super().__init__(*args, timeout=timeout, **kwargs)
