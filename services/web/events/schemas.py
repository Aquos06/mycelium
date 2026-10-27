"""The events domain: one bus event as the browser sees it, the page of recent ones, the socket frames.

Two kinds travel the socket. An `event` is a bus message the gateway keeps (seq, the replay buffer); a
`stream` frame is live text of a reply being written (stream.llm): forwarded as it comes, never kept, never
numbered, so a page that reconnects fetches the gap of events and simply waits for the reply itself.
"""

from __future__ import annotations

from typing import Any, Literal

from ..schemas import WebSchema


class BusEvent(WebSchema):
    seq: int  # this gateway's own counter; the socket's `after` cursor
    subject: str
    data: dict[str, Any]  # the publisher's payload, whatever its shape
    received: str  # UTC ISO-8601, when the gateway saw it


class StreamEvent(WebSchema):
    subject: str  # stream.llm
    data: dict[str, Any]  # gateway.schemas.StreamDelta: cause, request, seq, text, done


class EventsPage(WebSchema):
    ok: Literal[True] = True
    seq: int  # the newest event the buffer holds
    events: list[BusEvent]


class Hello(WebSchema):
    type: Literal["hello"] = "hello"
    seq: int  # the last event the buffer holds; fetch /events?after=<what you have> for the gap
    name: str


class Frame(WebSchema):
    type: Literal["event"] = "event"
    seq: int
    subject: str
    data: dict[str, Any]
    received: str


class StreamFrame(WebSchema):
    type: Literal["stream"] = "stream"
    subject: str
    data: dict[str, Any]
