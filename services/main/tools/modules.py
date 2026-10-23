"""`ask_module`: exact data from a deployed module over rpc.mod.<module>.<action>.

v0 has one generic tool and lists the modules in the prompt. Later each request in a module's
manifest becomes its own tool here (expenses.summary with its own argument model).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .base import Tool, ToolContext

NAME = r"^[a-z][a-z0-9_-]{0,40}$"  # a module or request name; also keeps the subject clean


class AskModuleArgs(BaseModel):
    module: str = Field(pattern=NAME, description="module name, as listed under Modules")
    action: str = Field(description="one of that module's requests: `stats` or `hello.stats`, both work")
    args: dict[str, Any] = Field(default_factory=dict, description="the request's arguments")

    @model_validator(mode="after")
    def _action_without_the_module_prefix(self) -> AskModuleArgs:
        """The prompt lists requests as `<module>.<action>`; the planner may hand that back whole."""
        self.action = self.action.strip().removeprefix(f"{self.module}.")
        if not re.fullmatch(NAME, self.action):
            raise ValueError(f"action must match {NAME}")
        return self


async def ask_module(args: AskModuleArgs, ctx: ToolContext) -> dict[str, Any]:
    return await ctx.bus.request(f"rpc.mod.{args.module}.{args.action}", args.args, timeout=10.0)


ASK_MODULE = Tool(
    name="ask_module",
    description=(
        "Ask a deployed module for exact data (numbers, lists, history). Memory only knows where data lives; "
        "the module has it. Use the module name and one of the requests listed under Modules."
    ),
    args=AskModuleArgs,
    handler=ask_module,
)
