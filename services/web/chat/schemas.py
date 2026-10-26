"""Request bodies and replies of the chat domain."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..schemas import WebSchema


class ChatIn(WebSchema):
    thread: str = Field(default="web", min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=8000)


class FeedbackIn(WebSchema):
    ref: str = Field(min_length=1, max_length=200)  # the out.ask id (its `ref`) or an out.say id for a vote
    thread: str = Field(default="web", min_length=1, max_length=120)
    answer: str | None = Field(default=None, max_length=2000)
    vote: int | None = Field(default=None, ge=-1, le=1)

    @model_validator(mode="after")
    def _one_of(self) -> FeedbackIn:
        if self.answer is None and self.vote is None:
            raise ValueError("an answer or a vote is needed")
        return self


class Sent(WebSchema):
    ok: Literal[True] = True
    id: str  # the envelope id the bus saw; Main's reply carries it as `cause`
    thread: str
