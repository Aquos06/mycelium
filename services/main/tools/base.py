"""A tool is a pydantic model for its arguments plus a handler.

The schema the planner sees is generated from the model, and every call is validated against the
same model before anything touches the bus. A rejected call goes back to the planner as a tool
error with the field path, so it can correct itself in the next round.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SkipValidation, ValidationError

from mycelium_sdk import Bus, input_schema, validation_message

NAME_PATTERN = r"^[a-z][a-z0-9_]{0,40}$"

__all__ = ["Tool", "ToolContext", "ToolOutcome", "ToolRegistry", "ToolSpec", "input_schema", "validation_message"]


class ToolContext(BaseModel):
    """What a handler may use: the bus and Main's settings. Built once per service."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    bus: SkipValidation[Bus]
    recall_budget: int = Field(default=8, ge=1)
    source: str = "hansen"  # who the facts come from when the planner writes memory


Handler = Callable[[Any, ToolContext], Awaitable[dict[str, Any]]]


class ToolSpec(BaseModel):
    """One entry of the `tools` array sent to the model (Anthropic shape)."""

    name: str
    description: str
    input_schema: dict[str, Any]


class Tool(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    name: str = Field(pattern=NAME_PATTERN)
    description: str = Field(min_length=1)
    args: type[BaseModel]
    handler: Handler = Field(exclude=True, repr=False)

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, input_schema=input_schema(self.args))

    def parse(self, raw: Mapping[str, Any]) -> BaseModel:
        return self.args.model_validate(dict(raw))

    async def run(self, args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
        return await self.handler(args, ctx)


class ToolOutcome(BaseModel):
    """One call as the planner made it, what it parsed to, and what went back. Dumps as the trace entry."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    args: BaseModel | None = Field(default=None, exclude=True)  # the validated arguments; None when rejected
    result: dict[str, Any]

    @property
    def ok(self) -> bool:
        return bool(self.result.get("ok"))

    def tool_result(self, tool_use_id: str, limit: int) -> dict[str, Any]:
        """The tool_result block for the next planner round."""
        content = json.dumps(self.result, ensure_ascii=False, default=str)[:limit]
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}


class ToolRegistry(BaseModel):
    tools: dict[str, Tool] = Field(default_factory=dict)

    @classmethod
    def of(cls, *tools: Tool) -> ToolRegistry:
        return cls(tools={t.name: t for t in tools})

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    @property
    def names(self) -> set[str]:
        return set(self.tools)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self.tools.values()]

    async def call(self, name: str, raw: Mapping[str, Any] | None, ctx: ToolContext) -> ToolOutcome:
        """Validate, run, and never raise: whatever happens becomes a result the planner can read."""
        raw = dict(raw or {})
        tool = self.tools.get(name)
        if tool is None:
            error = f"unknown tool {name!r}; available: {sorted(self.tools)}"
            return ToolOutcome(name=name, input=raw, result={"ok": False, "error": error})
        try:
            args = tool.parse(raw)
        except ValidationError as e:
            return ToolOutcome(name=name, input=raw, result={"ok": False, "error": validation_message(e, "input")})
        try:
            result = await tool.run(args, ctx)
        except Exception as e:
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return ToolOutcome(name=name, input=raw, args=args, result=result)
