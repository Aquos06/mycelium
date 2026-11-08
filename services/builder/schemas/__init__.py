"""Every shape the builder speaks, in one place (same layout as memory's and the gateway's schemas/).

rpc.py          rpc.build.* requests and replies: BuildListRequest, BuildList, CoderList, ... (and the SDK's below)
coder.py        a coder's round: Feedback, CoderContext, CoderResult; our coder's tool arguments: ManifestDraft, WriteFiles
supervisor.py   what the builder asks the supervisor (rpc.sys.*): VerifyCall, AgentCall, ... and the replies
gateway.py      what our coder asks the gateway before a build (rpc.llm.config)

One build and what is said about it are the SDK's (mycelium_sdk.build), re-exported here, since Main and mctl
read them too: BuildRecord, Round, BuildSummary, the stages, BuildRequest, StartReply, BuildRef, and the build.*
events, each built from the record (`BuildStage.of(record, ...)`): BuildStarted, BuildStage, BuildProgress,
BuildDone and BuildFailed (both BuildEnded), with RoundLine, and build.coder (CoderChosen). The model calls (Prompt, CompletionRequest,
ChatMessage, Tool, CompletionReply) and ask() are the SDK's too.
"""

from mycelium_sdk.build import (
    BuildDone,
    BuildEnded,
    BuildEvent,
    BuildFailed,
    BuildMode,
    BuildProgress,
    BuildRecord,
    BuildStage,
    BuildStarted,
    BuildStatus,
    BuildSummary,
    CoderChosen,
    FeedbackStage,
    Round,
    RoundLine,
    Stage,
)

from .coder import CoderContext, CoderResult, Feedback, FileArg, ManifestDraft, Spend, WriteFiles
from .gateway import ConfigReply, ProviderState, SlotState
from .rpc import (
    SPEC_MAX,
    BuildList,
    BuildListRequest,
    BuildRef,
    BuildRequest,
    CoderChoice,
    CoderInfo,
    CoderList,
    CoderSetting,
    StartReply,
)
from .supervisor import (
    AgentCall,
    AgentInfo,
    AgentReply,
    AgentsReply,
    DeployCall,
    DeployReply,
    ModuleEntry,
    ModulesReply,
    SnapshotCall,
    SnapshotReply,
    VerifyCall,
    VerifyReply,
)

__all__ = [
    "BuildMode",
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
    "BuildEnded",
    "BuildEvent",
    "BuildFailed",
    "BuildProgress",
    "BuildStage",
    "BuildStarted",
    "RoundLine",
    "ConfigReply",
    "ProviderState",
    "SlotState",
    "SPEC_MAX",
    "BuildList",
    "BuildListRequest",
    "BuildRef",
    "BuildRequest",
    "CoderChoice",
    "CoderChosen",
    "CoderInfo",
    "CoderList",
    "CoderSetting",
    "StartReply",
    "AgentCall",
    "AgentInfo",
    "AgentReply",
    "AgentsReply",
    "DeployCall",
    "DeployReply",
    "ModuleEntry",
    "ModulesReply",
    "SnapshotCall",
    "SnapshotReply",
    "VerifyCall",
    "VerifyReply",
]
