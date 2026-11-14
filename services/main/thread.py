"""Conversation threads: working memory, kept in NATS KV (docs/MEMORY.md §5).

One thread per (channel, thread id). Only the last `max_turns` turns are kept; anything worth
keeping longer goes to the vault through `remember`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, tzinfo
from typing import Any

from pydantic import BaseModel, Field

from mycelium_sdk import KV, ChatMessage, Role, TextBlock, ToolResult, ToolUse, kv_key, now_iso

RESULT_KEPT = 200  # characters of a tool's result kept in the thread: enough to show it went through
INPUT_KEPT = 300  # characters of each text argument kept (a proposal's spec parts are long)


class TurnCall(BaseModel):
    """A tool call made during an assistant turn. Kept so the planner sees what was done, not only what was said:
    with replies alone ("Logged: 152") a model learns to say it without doing it."""

    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    result: str = ""  # the start of what came back

    @classmethod
    def of(cls, name: str, input: dict[str, Any], result: dict[str, Any]) -> TurnCall:
        short = {k: v[:INPUT_KEPT] + "…" if isinstance(v, str) and len(v) > INPUT_KEPT else v for k, v in input.items()}
        return cls(name=name, input=short, result=json.dumps(result, ensure_ascii=False, default=str)[:RESULT_KEPT])


class Turn(BaseModel):
    role: Role
    text: str
    ts: str
    id: str | None = None  # the bus message id this turn came from
    calls: list[TurnCall] = Field(default_factory=list)  # an assistant turn's tool calls, in order
    unasked: bool = False  # Main said it on its own (a wake), not as an answer


class Thread(BaseModel):
    channel: str
    thread: str
    turns: list[Turn] = Field(default_factory=list)
    updated: str | None = None

    @property
    def key(self) -> str:
        return kv_key("thread", self.channel, self.thread)

    def messages(self, tz: tzinfo = UTC) -> list[ChatMessage]:
        """The turns as the planner's earlier messages, from a user turn on, roles alternating.

        Each of Hansen's messages starts with its date ("[Tue 2026-10-27] today i spent 112"), so a "today" in an
        old message means that day. What Main said on its own starts with when, marked as unasked ("[unasked, Tue
        2026-10-27 15:33] expenses: Nothing logged today."): it often follows an answer in the same message, and
        without the mark the two read as one reply. An assistant turn that called tools replays them: its tool_use
        blocks, their results, then what it said. Turns of the same role in a row (a build's result is an assistant
        turn of its own; chat templates and Anthropic's API refuse two in a row) become one message, and a thread
        trimmed to an assistant turn starts at the next user one."""
        out: list[tuple[Role, list[TextBlock | ToolUse | ToolResult]]] = []

        def add(role: Role, blocks: list[TextBlock | ToolUse | ToolResult]) -> None:
            if out and out[-1][0] == role:
                out[-1][1].extend(blocks)
            else:
                out.append((role, list(blocks)))

        for n, t in enumerate(self.turns):
            if not out and t.role != Role.USER:
                continue
            if t.role == Role.USER:
                add(Role.USER, [TextBlock(text=_dated(t, tz))])
                continue
            if t.calls:
                ids = [f"h{n:04d}c{i:03d}" for i in range(len(t.calls))]  # 9 characters: some templates insist
                add(
                    Role.ASSISTANT,
                    [ToolUse(id=i, name=c.name, input=c.input) for i, c in zip(ids, t.calls, strict=True)],
                )
                add(Role.USER, [ToolResult(tool_use_id=i, content=c.result) for i, c in zip(ids, t.calls, strict=True)])
            text = _dated(t, tz, "unasked, ", " %H:%M") if t.unasked else t.text
            add(Role.ASSISTANT, [TextBlock(text=text or "(no reply)")])
        return [_message(role, blocks) for role, blocks in out]


def _dated(turn: Turn, tz: tzinfo, mark: str = "", clock: str = "") -> str:
    try:
        ts = datetime.fromisoformat(turn.ts)
    except ValueError:
        return f"[{mark.rstrip(', ')}] {turn.text}" if mark else turn.text
    day = (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).astimezone(tz)
    return f"[{mark}{day.strftime('%a %Y-%m-%d' + clock)}] {turn.text}"


def _message(role: Role, blocks: list[TextBlock | ToolUse | ToolResult]) -> ChatMessage:
    """Text alone stays a plain string (every provider reads that), blocks only where a tool call needs them."""
    if all(isinstance(b, TextBlock) for b in blocks):
        return ChatMessage(role=role, content="\n\n".join(b.text for b in blocks if isinstance(b, TextBlock)))
    return ChatMessage(role=role, content=blocks)


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
