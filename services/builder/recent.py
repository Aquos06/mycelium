"""Recent: an answer kept a few seconds, and one question in flight however many callers ask at once.

Listing the coders asks each one, at the same time, whether it can build and what it is. An agent coder asks the
supervisor (rpc.sys.agents) and ours asks the gateway (rpc.llm.config) for both, so through a Recent that is one
question to each service per listing, not one per call per coder.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class Recent(Generic[T]):
    def __init__(self, fetch: Callable[[], Awaitable[T | None]], ttl: float) -> None:
        self.fetch = fetch
        self.ttl = ttl  # seconds an answer is kept; 0: only callers that ask together share one
        self._value: T | None = None
        self._at: float | None = None
        self._asking: asyncio.Task[T | None] | None = None

    async def get(self) -> T | None:
        """The answer. None, or an exception from `fetch`, is not kept: the next call asks again."""
        if self._at is not None and time.monotonic() - self._at <= self.ttl:
            return self._value
        if self._asking is None:
            self._asking = asyncio.create_task(self._ask())
        task = self._asking
        try:
            return await asyncio.shield(task)  # a caller that gives up does not cancel the others' question
        finally:
            if task.done() and self._asking is task:
                self._asking = None

    async def _ask(self) -> T | None:
        value = await self.fetch()
        if value is not None:
            self._value, self._at = value, time.monotonic()
        return value
