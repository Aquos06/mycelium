"""What every provider looks like to the service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from ..schemas import CompletionRequest, CompletionResult, DecideRequest, DecideResult, EmbedRequest, EmbedResult

#: Called with each piece of the reply's text as the model produces it (gateway.stream.TextStreamer.on_text).
#: A provider that cannot stream ignores it and answers whole; the caller never depends on it being called.
OnText = Callable[[str], Awaitable[None]]


class ProviderError(RuntimeError):
    """The vendor call failed (no key, auth, network, unusable response). Reaches the caller as ok=false."""


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, req: CompletionRequest, on_text: OnText | None = None) -> CompletionResult: ...


class EmbeddingProvider(Protocol):
    name: str
    model: str

    async def embed(self, req: EmbedRequest) -> EmbedResult: ...


class DecideProvider(Protocol):
    name: str
    model: str

    async def decide(self, req: DecideRequest) -> DecideResult: ...
