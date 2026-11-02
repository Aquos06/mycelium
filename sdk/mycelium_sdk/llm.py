"""rpc.llm.complete as every service speaks it: the messages, the tools, the request and the reply.

The wire format is the Anthropic Messages shape, because it is the richer one (the gateway converts for vendors
that speak something else):

    ChatMessage        {"role": Role, "content": str | [TextBlock | ToolUse | ToolResult, ...]}
    ToolSpec           {"name", "description", "input_schema"}: one entry of `tools`
    Tool               a tool whose arguments are a model: spec() offers it, parse() validates what came back
    CompletionRequest  what a caller sends; the gateway validates the same model on its side
    CompletionResult   what a provider returns, vendor differences smoothed out
    CompletionReply    the reply on the bus (the handler adds ok=true): the result, who served it, what it cost

A Prompt (prompt.py) is where a call starts: system=prompt.system, messages=[ChatMessage(role=Role.USER,
content=prompt.user)]; a tool-use loop then appends the assistant's ToolUse and the ToolResult that answers it.
The blocks' `type` stays a Literal: it is the tag that tells them apart, not a choice.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import input_schema

TOOL_NAME = r"^[a-z][a-z0-9_]{0,40}$"


# ---- the messages ------------------------------------------------------------------------------------


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolUse(BaseModel):
    """The assistant calling a tool (sent back as part of the conversation)."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The answer to a ToolUse, in the next user message."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str


Block = Annotated[TextBlock | ToolUse | ToolResult, Field(discriminator="type")]


class ChatMessage(BaseModel):
    role: Role
    content: str | list[Block]


# ---- the tools ---------------------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """One entry of the request's `tools`."""

    name: str
    description: str
    input_schema: dict[str, Any]  # a JSON schema


class Tool(BaseModel):
    """A tool whose arguments are a pydantic model: the model is offered spec(), and what it sends is parse()d."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=TOOL_NAME)
    description: str = Field(min_length=1)
    args: type[BaseModel]

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, input_schema=input_schema(self.args))

    def parse(self, raw: Mapping[str, Any] | None) -> BaseModel:
        return self.args.model_validate(dict(raw or {}))


class ToolCall(BaseModel):
    """A tool call in a reply."""

    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)  # {"_raw": ...} when the arguments were not valid JSON


# ---- the call ----------------------------------------------------------------------------------------


class CompletionRequest(BaseModel):
    slot: str = "planner"
    system: str = ""
    messages: list[ChatMessage] = Field(min_length=1)
    tools: list[ToolSpec] = Field(default_factory=list)
    tool_choice: str | None = None  # force this tool (by name): the reply is then always that tool call
    max_tokens: int | None = Field(default=None, ge=1)  # None: the provider's setting in providers.yaml
    temperature: float | None = Field(default=None, ge=0, le=2)
    cause: str | None = None  # id of the message this call serves; copied to trace.llm
    hops: int = Field(default=0, ge=0)  # that message's hops; trace.llm is one step further down
    timeout: float | None = Field(default=None, gt=0)  # seconds the caller waits; the gateway gives up first
    stream: bool = False  # publish the text on stream.llm as it is produced (needs a cause to match it by)

    @model_validator(mode="after")
    def _tool_choice_is_offered(self) -> CompletionRequest:
        if self.tool_choice is not None and self.tool_choice not in {t.name for t in self.tools}:
            raise ValueError(f"tool_choice {self.tool_choice!r} is not one of the tools offered")
        return self


class Usage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class CompletionResult(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str = "end_turn"  # end_turn | tool_use | max_tokens
    model: str
    usage: Usage = Field(default_factory=Usage)


class CompletionReply(CompletionResult):
    provider: str | None = None  # the gateway always says; a reader does not need it
    cost_usd: float = Field(default=0.0, ge=0)
