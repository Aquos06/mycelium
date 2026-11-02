"""Every shape the builder speaks, in one place (same layout as memory's and the gateway's schemas/).

build.py        one build: BuildRecord, Round, BuildSummary, the stages
rpc.py          rpc.build.* requests and replies: BuildRequest, StartReply, BuildRef, BuildListRequest, BuildList, ...
events.py       the build.* events: BuildStarted, BuildProgress, BuildDone, BuildFailed
coder.py        a coder's round: Feedback, CoderContext, CoderResult; our coder's tool arguments: ManifestDraft, WriteFiles
supervisor.py   what the builder asks the supervisor (rpc.sys.*): VerifyCall, AgentCall, ... and the replies
gateway.py      what our coder asks the gateway before a build (rpc.llm.config)

The model calls (Prompt, CompletionRequest, ChatMessage, Tool, CompletionReply) and ask() are the SDK's.
"""

from .build import BuildRecord, BuildStatus, BuildSummary, FeedbackStage, Round, Stage
from .coder import CoderContext, CoderResult, Feedback, FileArg, ManifestDraft, Spend, WriteFiles
from .events import BuildDone, BuildEvent, BuildFailed, BuildProgress, BuildStarted
from .gateway import ConfigReply, ProviderState, SlotState
from .rpc import SPEC_MAX, BuildList, BuildListRequest, BuildRef, BuildRequest, CoderInfo, CoderList, StartReply
from .supervisor import (
    AgentCall,
    AgentInfo,
    AgentReply,
    AgentsReply,
    DeployCall,
    DeployReply,
    ModuleEntry,
    ModulesReply,
    VerifyCall,
    VerifyReply,
)

__all__ = [
    "BuildRecord",
    "BuildStatus",
    "BuildSummary",
    "FeedbackStage",
    "Round",
    "Stage",
    "CoderContext",
    "CoderResult",
    "Feedback",
    "FileArg",
    "ManifestDraft",
    "Spend",
    "WriteFiles",
    "BuildDone",
    "BuildEvent",
    "BuildFailed",
    "BuildProgress",
    "BuildStarted",
    "ConfigReply",
    "ProviderState",
    "SlotState",
    "SPEC_MAX",
    "BuildList",
    "BuildListRequest",
    "BuildRef",
    "BuildRequest",
    "CoderInfo",
    "CoderList",
    "StartReply",
    "AgentCall",
    "AgentInfo",
    "AgentReply",
    "AgentsReply",
    "DeployCall",
    "DeployReply",
    "ModuleEntry",
    "ModulesReply",
    "VerifyCall",
    "VerifyReply",
]
