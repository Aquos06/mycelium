"""What every provider looks like to the service."""

from __future__ import annotations

from typing import Protocol

from ..schemas import CompletionRequest, CompletionResult, EmbedRequest, EmbedResult


class ProviderError(RuntimeError):
    """The vendor call failed (no key, auth, network, unusable response). Reaches the caller as ok=false."""


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, req: CompletionRequest) -> CompletionResult: ...


class EmbeddingProvider(Protocol):
    name: str
    model: str

    async def embed(self, req: EmbedRequest) -> EmbedResult: ...
