"""Every shape the gateway speaks, in one place.

kinds.py        the provider kinds: protocol, default endpoint and key env var per vendor
config.py       providers.yaml: GatewayConfig -> SlotConfig -> ProviderConfig
embedding.py    rpc.llm.embed: EmbedRequest in, EmbedResult from a provider, EmbedReply out
decide.py       rpc.llm.decide: a question and candidates in, a score per candidate out
completion.py   rpc.llm.complete: CompletionRequest in, CompletionResult from a provider, CompletionReply out
usage.py        the monthly spend counter in KV and the rpc.llm.usage reply
trace.py        what goes on trace.llm and trace.llm.shadow
"""

from .completion import ROLES, CompletionReply, CompletionRequest, CompletionResult, ToolCall, Usage
from .config import GatewayConfig, KeyState, ProviderConfig, SlotConfig, SlotTask
from .decide import Candidate, DecideReply, DecideRequest, DecideResult, Score, ScoreSheet
from .embedding import EmbedReply, EmbedRequest, EmbedResult
from .kinds import KINDS, KindInfo, Protocol, ProviderKind
from .trace import LlmTrace, ShadowResult, ShadowSide, ShadowTrace
from .usage import UsageRecord, UsageReply

__all__ = [
    "ROLES",
    "CompletionReply",
    "CompletionRequest",
    "CompletionResult",
    "ToolCall",
    "Usage",
    "GatewayConfig",
    "KeyState",
    "ProviderConfig",
    "SlotConfig",
    "SlotTask",
    "Candidate",
    "DecideReply",
    "DecideRequest",
    "DecideResult",
    "Score",
    "ScoreSheet",
    "EmbedReply",
    "EmbedRequest",
    "EmbedResult",
    "KINDS",
    "KindInfo",
    "Protocol",
    "ProviderKind",
    "LlmTrace",
    "ShadowResult",
    "ShadowSide",
    "ShadowTrace",
    "UsageRecord",
    "UsageReply",
]
