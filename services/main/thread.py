"""Conversation threads: working memory, kept in NATS KV (docs/MEMORY.md §5).

One thread per (channel, thread id). Only the last `max_turns` turns are kept; anything worth
keeping longer goes to the vault through `remember`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mycelium_sdk import KV, kv_key, now_iso


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    ts: str
    id: str | None = None  # the bus message id this turn came from


class Thread(BaseModel):
    channel: str
    thread: str
    turns: list[Turn] = Field(default_factory=list)
    updated: str | None = None

    @property
    def key(self) -> str:
        return kv_key("thread", self.channel, self.thread)

    def messages(self) -> list[dict[str, str]]:
        """The turns in the gateway's message shape."""
        return [{"role": t.role, "content": t.text} for t in self.turns]


class ThreadStore:
    def __init__(self, kv: KV, max_turns: int = 20) -> None:
        self.kv = kv
        self.max_turns = max_turns

    async def load(self, channel: str, thread: str) -> Thread:
        raw = await self.kv.get(kv_key("thread", channel, thread))
        if raw is None:
            return Thread(channel=channel, thread=thread)
        return Thread.model_validate({**raw, "channel": channel, "thread": thread})

    async def save(self, thread: Thread) -> None:
        thread.turns = thread.turns[-self.max_turns :]
        thread.updated = now_iso()
        await self.kv.put(thread.key, thread.model_dump())

    async def append(self, thread: Thread, *turns: Turn) -> None:
        thread.turns.extend(turns)
        await self.save(thread)

    async def clear(self, channel: str, thread: str) -> None:
        await self.kv.delete(kv_key("thread", channel, thread))
