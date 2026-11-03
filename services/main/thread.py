"""Conversation threads: working memory, kept in NATS KV (docs/MEMORY.md §5).

One thread per (channel, thread id). Only the last `max_turns` turns are kept; anything worth
keeping longer goes to the vault through `remember`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mycelium_sdk import KV, ChatMessage, Role, kv_key, now_iso


class Turn(BaseModel):
    role: Role
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

    def messages(self) -> list[ChatMessage]:
        """The turns as the planner's earlier messages: from a user turn on, roles alternating. A build's result is
        an assistant turn of its own, and chat templates (and Anthropic's API) refuse two in a row, so turns of the
        same role in a row become one message; a thread trimmed to an assistant turn starts at the next user one."""
        out: list[ChatMessage] = []
        for t in self.turns:
            if not out and t.role != Role.USER:
                continue
            if out and out[-1].role == t.role:
                out[-1] = ChatMessage(role=t.role, content=f"{out[-1].content}\n\n{t.text}")
            else:
                out.append(ChatMessage(role=t.role, content=t.text))
        return out


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
