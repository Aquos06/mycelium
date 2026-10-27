"""Live text of a reply on `stream.llm`, as the model produces it (ARCHITECTURE §10: the chat streams).

Batched: a frame every FLUSH_MS or every FLUSH_CHARS, whichever comes first, so a reply is a handful of
messages rather than one per token. `stream.` is not an event: no envelope, not in the EVENTS stream, the
tracer skips it. It is only ever read live, by whoever is showing the reply being written: the web app
matches frames to its own message by `cause`. The final frame says `done`, with whatever text was left.

A failure to publish never fails the completion: the reply still arrives whole on rpc.llm.complete.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable

from mycelium_sdk import Bus

from .schemas import StreamDelta

log = logging.getLogger("mycelium.gateway")

SUBJECT = "stream.llm"
FLUSH_MS = 120
FLUSH_CHARS = 48


class TextStreamer:
    def __init__(
        self,
        bus: Bus,
        *,
        cause: str,
        slot: str,
        provider: str,
        flush_ms: int = FLUSH_MS,
        flush_chars: int = FLUSH_CHARS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bus = bus
        self.head = StreamDelta(cause=cause, request=uuid.uuid4().hex[:12], slot=slot, provider=provider, seq=0)
        self.flush_ms = flush_ms
        self.flush_chars = flush_chars
        self.clock = clock
        self._buf: list[str] = []
        self._size = 0
        self._seq = 0
        self._timer: asyncio.Task | None = None
        self._closed = False

    @property
    def request(self) -> str:
        return self.head.request

    async def on_text(self, text: str) -> None:
        """A piece of the reply. Sent now when the batch is full, otherwise with the next tick."""
        if self._closed or not text:
            return
        self._buf.append(text)
        self._size += len(text)
        if self._size >= self.flush_chars:
            await self.flush()
        elif self._timer is None or self._timer.done():
            self._timer = asyncio.create_task(self._tick())

    async def _tick(self) -> None:
        await asyncio.sleep(self.flush_ms / 1000)
        await self.flush()

    async def flush(self, done: bool = False) -> None:
        if self._timer is not None and not self._timer.done() and asyncio.current_task() is not self._timer:
            self._timer.cancel()
        text = "".join(self._buf)
        self._buf.clear()
        self._size = 0
        if not text and not done:
            return
        self._seq += 1
        frame = self.head.model_copy(update={"seq": self._seq, "text": text, "done": done})
        try:
            await self.bus.publish(SUBJECT, frame)
        except Exception:  # the stream is a courtesy; the reply still comes back whole
            log.warning("stream.llm publish failed for cause=%s", self.head.cause, exc_info=True)

    async def close(self) -> None:
        """The last frame: whatever is buffered, marked done. Idempotent."""
        if self._closed:
            return
        self._closed = True
        await self.flush(done=True)
