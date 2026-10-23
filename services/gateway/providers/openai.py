"""OpenAI itself (api.openai.com).

Same wire shape as the generic provider with one difference: current models take
`max_completion_tokens`, and the reasoning models reject `max_tokens` outright. Model-specific
knobs (reasoning_effort, verbosity, ...) go through `extra_body` in providers.yaml.
"""

from __future__ import annotations

from .openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    max_tokens_field = "max_completion_tokens"
