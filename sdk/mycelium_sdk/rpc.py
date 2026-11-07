"""ask(): one request to another service, its answer read into a model.

    reply = await ask(bus, "rpc.sys.verify", VerifyCall(name=name), VerifyReply, timeout=900)

Every rpc.* handler answers {"ok": true, ...} or {"ok": false, "error"}: a responder sends Answer.of(result) or
Refusal(error=...). NoAnswer when nobody answers in time, Refused when the answer is {"ok": false} or does not
read as the reply model; each caller turns them into its own error.
"""

from __future__ import annotations

from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from .bus import Bus
from .validation import validation_message

R = TypeVar("R", bound=BaseModel)


class Answer(BaseModel):
    """{"ok": true, ...}: a responder's result as it goes back, its own fields next to `ok`."""

    model_config = ConfigDict(extra="allow")

    ok: Literal[True] = True

    @classmethod
    def of(cls, result: BaseModel) -> Answer:
        return cls.model_validate(result.model_dump(mode="json"))


class Refusal(BaseModel):
    """{"ok": false, "error"}: a responder that will not, and why."""

    ok: Literal[False] = False
    error: str


class NoAnswer(Exception):
    """Nobody answered in time: the service is down, restarting, or still working. The message says how it
    failed (TimeoutError, NoRespondersError)."""


class Refused(Exception):
    """It answered {"ok": false, "error"}, or with something that does not read as the reply."""


async def ask(bus: Bus, subject: str, call: BaseModel | None, reply: type[R], timeout: float) -> R:
    try:
        raw = await bus.request(subject, call if call is not None else {}, timeout=timeout)
    except Exception as e:
        raise NoAnswer(type(e).__name__) from e
    if not raw.get("ok"):
        raise Refused(str(raw.get("error") or "refused"))
    try:
        return reply.model_validate(raw)
    except ValidationError as e:
        raise Refused(f"an answer that does not read as {reply.__name__}: {validation_message(e, 'reply')}") from e
