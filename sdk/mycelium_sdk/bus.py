"""Bus abstraction. Everything talks through this, never through nats directly,
so the transport can be swapped and modules can be unit-tested in memory."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .subjects import subject_matches


@dataclass
class Message:
    subject: str
    data: dict[str, Any]
    reply: str | None = None
    _respond: Callable[[dict[str, Any]], Awaitable[None]] | None = field(default=None, repr=False)

    async def respond(self, data: dict[str, Any]) -> None:
        if self._respond is None:
            raise RuntimeError(f"message on {self.subject} has no reply address")
        await self._respond(data)


Handler = Callable[[Message], Awaitable[None]]


class Bus(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def publish(self, subject: str, data: dict[str, Any]) -> None: ...
    async def subscribe(self, subject: str, handler: Handler, queue: str | None = None) -> None: ...
    async def request(self, subject: str, data: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]: ...


def _encode(data: dict[str, Any]) -> bytes:
    return json.dumps(data, default=str).encode()


def _decode(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw.decode(errors="replace")}
    return value if isinstance(value, dict) else {"value": value}


class NatsBus:
    """Real bus backed by NATS."""

    def __init__(self, url: str = "nats://localhost:4222", name: str | None = None):
        self.url = url
        self.name = name
        self._nc = None

    async def connect(self) -> None:
        import nats  # imported lazily so unit tests never need a server

        self._nc = await nats.connect(self.url, name=self.name, max_reconnect_attempts=-1)

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
            self._nc = None

    @property
    def nc(self):
        if self._nc is None:
            raise RuntimeError("bus not connected")
        return self._nc

    async def publish(self, subject: str, data: dict[str, Any]) -> None:
        await self.nc.publish(subject, _encode(data))

    async def subscribe(self, subject: str, handler: Handler, queue: str | None = None) -> None:
        async def _cb(msg):
            async def _respond(payload: dict[str, Any]) -> None:
                await msg.respond(_encode(payload))

            await handler(
                Message(
                    subject=msg.subject,
                    data=_decode(msg.data),
                    reply=msg.reply or None,
                    _respond=_respond if msg.reply else None,
                )
            )

        await self.nc.subscribe(subject, queue=queue or "", cb=_cb)

    async def request(self, subject: str, data: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
        msg = await self.nc.request(subject, _encode(data), timeout=timeout)
        return _decode(msg.data)

    async def flush(self) -> None:
        await self.nc.flush()


class InMemoryBus:
    """Test double with NATS-like wildcard semantics. Records everything published."""

    def __init__(self) -> None:
        self._subs: list[tuple[str, Handler]] = []
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        self._subs.clear()

    async def publish(self, subject: str, data: dict[str, Any]) -> None:
        self.published.append((subject, data))
        for pattern, handler in list(self._subs):
            if subject_matches(pattern, subject):
                await handler(Message(subject=subject, data=data))

    async def subscribe(self, subject: str, handler: Handler, queue: str | None = None) -> None:
        self._subs.append((subject, handler))

    async def request(self, subject: str, data: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()

        async def _respond(payload: dict[str, Any]) -> None:
            if not fut.done():
                fut.set_result(payload)

        for pattern, handler in list(self._subs):
            if subject_matches(pattern, subject):
                await handler(Message(subject=subject, data=data, reply="_INBOX.mem", _respond=_respond))
                break
        else:
            raise TimeoutError(f"no responders for {subject}")
        return await asyncio.wait_for(fut, timeout)

    def events(self, pattern: str = ">") -> list[tuple[str, dict[str, Any]]]:
        return [(s, d) for s, d in self.published if subject_matches(pattern, s)]
