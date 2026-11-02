"""What our coder asks the gateway before a build, and the answer as it reads it.

    rpc.llm.config    {}   -> ConfigReply   (the gateway's ConfigReply: is the coder slot there, has it a key)

The model calls themselves (rpc.llm.complete) are the SDK's: CompletionRequest, ChatMessage, CompletionReply in
mycelium_sdk.llm, the same models every service sends and the gateway validates.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProviderState(BaseModel):
    key_state: str  # ok | missing | not-needed


class SlotState(BaseModel):
    active: str
    providers: dict[str, ProviderState] = Field(default_factory=dict)


class ConfigReply(BaseModel):
    slots: dict[str, SlotState] = Field(default_factory=dict)
