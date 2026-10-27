"""What every provider looks like to the service."""

from __future__ import annotations

from typing import Protocol

from ..schemas import CompletionRequest, CompletionResult, DecideRequest, DecideResult, EmbedRequest, EmbedResult


class StreamSink(Protocol):
    """Where a provider puts the reply as the model produces it (gateway.stream.TextStreamer).

    A provider that cannot stream ignores it and answers whole; the caller never depends on it being called.
    """

    async def on_text(self, text: str) -> None: ...  # a piece of the reply

    async def on_thinking(self, text: str) -> None: ...  # a piece of a reasoning model's thinking, never the reply


class ProviderError(RuntimeError):
    """The vendor call failed (no key, auth, network, unusable response). Reaches the caller as ok=false."""


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, req: CompletionRequest, sink: StreamSink | None = None) -> CompletionResult: ...


class EmbeddingProvider(Protocol):
    name: str
    model: str

    async def embed(self, req: EmbedRequest) -> EmbedResult: ...


class DecideProvider(Protocol):
    name: str
    model: str

    async def decide(self, req: DecideRequest) -> DecideResult: ...
