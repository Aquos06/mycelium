"""The one way this job talks to a model: a forced tool call through the gateway, validated on return.

An invalid answer goes back once with the field errors, as a tool_result, so the model can correct it.
Rounds, model and cost land on the caller's report even when the call ends in an error.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from mycelium_sdk import Bus, validation_message

from ..schemas import ModelRequest
from .errors import ConsolidationError
from .prompts import Prompt
from .tools import StructuredTool

log = logging.getLogger("mycelium.memory.consolidate")

T = TypeVar("T", bound=BaseModel)


class Billable(Protocol):
    """What a report must carry for the caller to account the call: both report models do."""

    rounds: int
    model: str | None
    cost_usd: float


class ModelCaller:
    def __init__(
        self,
        bus: Bus,
        slot: str = "consolidate",
        timeout: float = 180.0,
        max_tokens: int | None = None,  # None: the provider's own max_tokens from providers.yaml decides
        max_rounds: int = 2,
    ) -> None:
        self.bus = bus
        self.slot = slot
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.max_rounds = max_rounds

    async def ask(self, prompt: Prompt, tool: StructuredTool, cause: str | None, report: Billable) -> BaseModel:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt.user}]
        error = ""
        for _round in range(self.max_rounds):
            request = ModelRequest(
                slot=self.slot,
                system=prompt.system,
                messages=messages,
                tools=[tool.spec()],
                tool_choice=tool.name,
                max_tokens=self.max_tokens,
                cause=cause,
                timeout=self.timeout,
            )
            try:
                reply = await self.bus.request("rpc.llm.complete", request, timeout=self.timeout + 5)
            except Exception as e:
                raise ConsolidationError(f"gateway unreachable: {type(e).__name__}: {e}") from e
            if not reply.get("ok"):
                raise ConsolidationError(str(reply.get("error") or "gateway error"))
            report.rounds += 1
            report.model = reply.get("model")
            report.cost_usd = round(report.cost_usd + float(reply.get("cost_usd") or 0), 6)
            calls = [c for c in reply.get("tool_calls") or [] if c.get("name") == tool.name]
            if not calls:
                raise ConsolidationError(f"model did not call {tool.name}")
            call = calls[0]
            try:
                return tool.parse(call.get("input"))
            except ValidationError as e:
                error = validation_message(e, "digest")
                log.warning("%s rejected (round %d): %s", tool.name, report.rounds, error)
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "id": call["id"], "name": tool.name, "input": call.get("input") or {}}
                        ],
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": call["id"],
                                "content": json.dumps({"ok": False, "error": error}, ensure_ascii=False),
                            }
                        ],
                    }
                )
        raise ConsolidationError(f"no valid digest after {self.max_rounds} rounds: {error}")
