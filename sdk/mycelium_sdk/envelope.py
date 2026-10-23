"""Message envelope (ARCHITECTURE cross-cutting rule 1).

Every message a host service publishes carries:

    id      unique, time-ordered, so traces can refer to it
    ts      when it was published (UTC ISO-8601)
    source  which component published it
    cause   the id of the message this one is a reaction to (None for a root event)
    hops    how many causal steps from the root; the loop breaker reads it

    Envelope(source="telegram").stamp(channel="telegram", text="hi")      # a root event, as a dict
    Envelope.child_of(msg.data, "main").stamp(text="reply")               # a reaction to msg
    Envelope.child_of(msg.data, "main").into(Say, text="reply")           # the same, as a typed message

`stamp()` returns the JSON object that goes on the bus; `into()` builds a typed message (a subclass
of Envelope) from it. The bus accepts either. Modules get this for free from the SDK later; for now
services build it themselves.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

E = TypeVar("E", bound="Envelope")


def new_id() -> str:
    """13 hex chars of milliseconds since the epoch, then 8 random hex chars: sorts by time."""
    return f"{time.time_ns() // 1_000_000:013x}{secrets.token_hex(4)}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Envelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_id)
    ts: str = Field(default_factory=now_iso)
    source: str
    cause: str | None = None
    hops: int = Field(default=0, ge=0)

    @classmethod
    def child_of(cls, parent: Mapping[str, Any] | Envelope, source: str) -> Envelope:
        """An envelope for a message caused by `parent`: any incoming payload, with or without an envelope."""
        if isinstance(parent, Envelope):
            return parent.child(source)
        cause = parent.get("id")
        return cls(source=source, cause=str(cause) if cause else None, hops=int(parent.get("hops") or 0) + 1)

    def child(self, source: str) -> Envelope:
        return Envelope(source=source, cause=self.id, hops=self.hops + 1)

    def stamp(self, **fields: Any) -> dict[str, Any]:
        """The envelope plus the message's own fields: the JSON object that goes on the bus."""
        return {**self.model_dump(mode="json"), **fields}

    def into(self, model: type[E], **fields: Any) -> E:
        """This envelope as a typed message: `model` is a subclass of Envelope, `fields` its own fields."""
        return model.model_validate({**self.model_dump(), **fields})
