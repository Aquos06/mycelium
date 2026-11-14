"""mycelium SDK: the one library every module and core service shares.

- bus:       Bus interface, NatsBus (real) and InMemoryBus (tests)
- kv:        KV interface, NatsKV (JetStream KV) and InMemoryKV (tests)
- envelope:  id / ts / source / cause / hops for every published message
- manifest:  module manifest schema + validation
- module:    Module base runtime (subscribe, answer requests, emit, observe, intervals, daily times)
- observe:   Observation and Severity, what a module tells Main on brain.observe and how loud
- clock:     next_daily and sleep_until, a time of day in the user's zone (import mycelium_sdk.clock)
- subjects:  subject naming helpers and wildcard matching
- validation: one formatter for pydantic errors in rpc replies
- schema:    a pydantic model as a tool's input_schema for a model
- prompt:    Prompt, the system text and the user message a model reads
- llm:       rpc.llm.complete for every service: ChatMessage and its blocks, ToolSpec, Tool, the request, the reply
- rpc:       ask(), one request to another service read into a model; NoAnswer, Refused
- build:     the builder's contract: BuildRequest, StartReply, BuildRef, BuildRecord, RemoveRequest, Removed and the
             build.* events, as the builder sends them and Main reads them (import mycelium_sdk.build)
- text:      cut and one_line, text made to fit a card or a prompt
- blocks:    a module's data as a table, a chart, stats, details or a meter: BlockSpec, build (import mycelium_sdk.blocks)
- views:     a module's views, declared in its manifest or suggested from its requests (import mycelium_sdk.views)
- notes:     NoteType, the kinds of note in memory's vault (memory files them, Main's remember offers them)
- settings:  ServiceSettings, the base for each service's environment (pydantic-settings)
- db:        the async SQLAlchemy engine, Alembic migrate(), the core tables (import mycelium_sdk.db)
"""

from .bus import Bus, InMemoryBus, Message, NatsBus, Payload
from .envelope import Envelope, new_id, now_iso
from .kv import KV, InMemoryKV, NatsKV, kv_key
from .llm import (
    ChatMessage,
    CompletionReply,
    CompletionRequest,
    CompletionResult,
    Role,
    TextBlock,
    Tool,
    ToolCall,
    ToolResult,
    ToolSpec,
    ToolUse,
    Usage,
)
from .manifest import Manifest, ManifestError, RequestSpec, load_manifest, validate_manifest
from .module import Module
from .notes import NoteType
from .observe import Observation, Severity
from .prompt import Prompt
from .rpc import Answer, NoAnswer, Refusal, Refused, ask
from .schema import input_schema
from .settings import ServiceSettings, timezone
from .subjects import subject_matches
from .text import cut, one_line
from .validation import validation_message

__all__ = [
    "Bus",
    "InMemoryBus",
    "NatsBus",
    "Message",
    "Payload",
    "KV",
    "InMemoryKV",
    "NatsKV",
    "kv_key",
    "Envelope",
    "new_id",
    "now_iso",
    "Manifest",
    "RequestSpec",
    "ManifestError",
    "load_manifest",
    "validate_manifest",
    "Module",
    "subject_matches",
    "cut",
    "one_line",
    "validation_message",
    "input_schema",
    "Prompt",
    "ChatMessage",
    "CompletionReply",
    "CompletionRequest",
    "CompletionResult",
    "Role",
    "TextBlock",
    "Tool",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "ToolUse",
    "Usage",
    "NoAnswer",
    "Refused",
    "Refusal",
    "Answer",
    "ask",
    "NoteType",
    "Observation",
    "Severity",
    "ServiceSettings",
    "timezone",
]
