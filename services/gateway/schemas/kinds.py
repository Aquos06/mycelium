"""The provider kinds the gateway knows: the protocol each speaks and its defaults.

    kind           protocol   default endpoint                                          key env
    claude         anthropic  (Anthropic SDK; set endpoint only to go through a proxy)   ANTHROPIC_API_KEY
    openai         openai     https://api.openai.com/v1                                 OPENAI_API_KEY
    ollama         openai     http://ollama:11434/v1                                    none, local
    vllm           openai     http://vllm:8000/v1                                       none, local
    tei            openai     http://tei:80/v1   (embeddings; /rerank for decide)       none, local
    openrouter     openai     https://openrouter.ai/api/v1                              OPENROUTER_API_KEY
    groq           openai     https://api.groq.com/openai/v1                            GROQ_API_KEY
    deepseek       openai     https://api.deepseek.com/v1                               DEEPSEEK_API_KEY
    mistral        openai     https://api.mistral.ai/v1                                 MISTRAL_API_KEY
    gemini         openai     https://generativelanguage.googleapis.com/v1beta/openai   GEMINI_API_KEY
    xai            openai     https://api.x.ai/v1                                       XAI_API_KEY
    openai_compat  openai     (set `endpoint`)                                          optional: set `key_env`

Two protocols cover every vendor: the Anthropic Messages shape (the gateway's own) and OpenAI chat
completions. A new vendor is one row here; it gets a class of its own in providers/ only when it
has quirks (providers/openai.py, ollama.py, vllm.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

ProviderKind = Literal[
    "claude",
    "openai",
    "ollama",
    "vllm",
    "tei",
    "openrouter",
    "groq",
    "deepseek",
    "mistral",
    "gemini",
    "xai",
    "openai_compat",
]
Protocol = Literal["anthropic", "openai"]


class KindInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ProviderKind
    protocol: Protocol
    endpoint: str | None = None  # default base URL; None: the SDK's own, or required in the config
    key_env: str | None = None  # default env var holding the key
    needs_key: bool = True
    local: bool = False  # runs next to the gateway: no key, no cost


KINDS: dict[ProviderKind, KindInfo] = {
    k.kind: k
    for k in (
        KindInfo(kind="claude", protocol="anthropic", key_env="ANTHROPIC_API_KEY"),
        KindInfo(kind="openai", protocol="openai", endpoint="https://api.openai.com/v1", key_env="OPENAI_API_KEY"),
        KindInfo(kind="ollama", protocol="openai", endpoint="http://ollama:11434/v1", needs_key=False, local=True),
        KindInfo(kind="vllm", protocol="openai", endpoint="http://vllm:8000/v1", needs_key=False, local=True),
        KindInfo(kind="tei", protocol="openai", endpoint="http://tei:80/v1", needs_key=False, local=True),
        KindInfo(
            kind="openrouter", protocol="openai", endpoint="https://openrouter.ai/api/v1", key_env="OPENROUTER_API_KEY"
        ),
        KindInfo(kind="groq", protocol="openai", endpoint="https://api.groq.com/openai/v1", key_env="GROQ_API_KEY"),
        KindInfo(
            kind="deepseek", protocol="openai", endpoint="https://api.deepseek.com/v1", key_env="DEEPSEEK_API_KEY"
        ),
        KindInfo(kind="mistral", protocol="openai", endpoint="https://api.mistral.ai/v1", key_env="MISTRAL_API_KEY"),
        KindInfo(
            kind="gemini",
            protocol="openai",
            endpoint="https://generativelanguage.googleapis.com/v1beta/openai",
            key_env="GEMINI_API_KEY",
        ),
        KindInfo(kind="xai", protocol="openai", endpoint="https://api.x.ai/v1", key_env="XAI_API_KEY"),
        KindInfo(kind="openai_compat", protocol="openai", needs_key=False),
    )
}
