"""WebGateway: the bus as the browser sees it. The body behind every router in this package.

Subscribes to every event prefix (never rpc.*), keeps the last few hundred events for a page that just
opened, fans each new one out to the connected sockets, and turns what the app says into bus messages
on channel "web": chat into sense.chat, an answer or a vote into sense.feedback. rpc() forwards a
request/reply to any rpc.* subject and returns the responder's own reply. Live stream.* frames (a reply
as the model writes it) are fanned out the same way but never kept.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from mycelium_sdk import Bus, Envelope, Message
from mycelium_sdk.subjects import EVENT_PREFIXES, STREAM_PREFIX

from .chat.schemas import ChatIn, FeedbackIn, Sent
from .events.schemas import BusEvent, StreamEvent
from .rpc.schemas import RpcIn
from .schemas import CHANNEL

log = logging.getLogger("mycelium.web")

RPC_RE = re.compile(r"^rpc(?:\.[A-Za-z0-9_-]+){2,}$")  # rpc.sys.list, rpc.mod.hello.stats, rpc.memory.recall
CLIENT_QUEUE = 1000  # frames a slow socket may fall behind before it is dropped

Outgoing = BusEvent | StreamEvent


class WebGateway:
    def __init__(self, bus: Bus, *, buffer: int = 300, rpc_timeout: float = 10.0) -> None:
        self.bus = bus
        self.rpc_timeout = rpc_timeout
        self.recent: deque[BusEvent] = deque(maxlen=buffer)
        self._seq = 0
        self._clients: set[asyncio.Queue[Outgoing | None]] = set()

    async def start(self) -> None:
        await self.bus.connect()
        for prefix in EVENT_PREFIXES:
            await self.bus.subscribe(prefix + ">", self._on_event)
        await self.bus.subscribe(STREAM_PREFIX + ">", self._on_stream)

    # ---- bus -> browser ---------------------------------------------------------------------

    async def _on_event(self, msg: Message) -> None:
        self._seq += 1
        ev = BusEvent(seq=self._seq, subject=msg.subject, data=msg.data, received=datetime.now(UTC).isoformat())
        self.recent.append(ev)
        self._fan_out(ev)

    async def _on_stream(self, msg: Message) -> None:
        self._fan_out(StreamEvent(subject=msg.subject, data=msg.data))  # live only: not numbered, not kept

    def _fan_out(self, item: Outgoing) -> None:
        for q in list(self._clients):
            if q.qsize() >= CLIENT_QUEUE:  # a socket that stopped reading: cut it loose, it will reconnect
                self._clients.discard(q)
                q.put_nowait(None)
                continue
            q.put_nowait(item)

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def clients(self) -> int:
        return len(self._clients)

    def attach(self) -> asyncio.Queue[Outgoing | None]:
        q: asyncio.Queue[Outgoing | None] = asyncio.Queue()
        self._clients.add(q)
        return q

    def detach(self, q: asyncio.Queue[Outgoing | None]) -> None:
        self._clients.discard(q)

    def events(self, limit: int | None = None, after: int = 0) -> list[BusEvent]:
        """The buffered events after `after` (a seq), oldest first, the last `limit` of them."""
        rows: Iterable[BusEvent] = (e for e in self.recent if e.seq > after)
        out = list(rows)
        return out[-limit:] if limit is not None and limit < len(out) else out

    # ---- browser -> bus ---------------------------------------------------------------------

    async def chat(self, req: ChatIn) -> Sent:
        env = Envelope(source=CHANNEL)
        await self.bus.publish("sense.chat", env.stamp(channel=CHANNEL, thread=req.thread, text=req.text))
        return Sent(id=env.id, thread=req.thread)

    async def feedback(self, req: FeedbackIn) -> Sent:
        env = Envelope(source=CHANNEL)
        fields: dict[str, Any] = {"channel": CHANNEL, "thread": req.thread, "ref": req.ref}
        if req.answer is not None:
            fields["answer"] = req.answer
        if req.vote is not None:
            fields["vote"] = req.vote
        await self.bus.publish("sense.feedback", env.stamp(**fields))
        return Sent(id=env.id, thread=req.thread)

    async def rpc(self, subject: str, req: RpcIn) -> dict[str, Any]:
        if not RPC_RE.match(subject):
            raise ValueError(f"not an rpc subject: {subject!r}")
        return await self.bus.request(subject, req.payload, timeout=req.timeout or self.rpc_timeout)
