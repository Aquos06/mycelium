"""vLLM on the GPU box (`docker compose --profile gpu up -d vllm`). Speaks the OpenAI shape on /v1.

- No key by default; set `key_env` when the server runs with --api-key.
- `model` is the Hugging Face id the server was started with (Qwen/Qwen2.5-14B-Instruct).
- Tool calling needs the server flags --enable-auto-tool-choice --tool-call-parser <hermes|llama3_json|mistral>;
  the compose service sets them.
- vLLM-only request fields (guided_json, chat_template_kwargs, ...) go through `extra_body` in providers.yaml.
"""

from __future__ import annotations

from .openai_compat import OpenAICompatProvider


class VLLMProvider(OpenAICompatProvider):
    """Nothing to override today; the class names the kind and is where vLLM quirks will live."""
