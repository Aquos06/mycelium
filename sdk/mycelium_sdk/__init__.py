"""mycelium SDK: the one library every module and core service shares.

- bus:       Bus interface, NatsBus (real) and InMemoryBus (tests)
- kv:        KV interface, NatsKV (JetStream KV) and InMemoryKV (tests)
- envelope:  id / ts / source / cause / hops for every published message
- manifest:  module manifest schema + validation
- module:    Module base runtime (subscribe, answer requests, emit, observe, intervals)
- subjects:  subject naming helpers and wildcard matching
- validation: one formatter for pydantic errors in rpc replies
- schema:    a pydantic model as a tool's input_schema for a model
- prompt:    Prompt, the system text and the user message a model reads
- llm:       rpc.llm.complete for every service: ChatMessage and its blocks, ToolSpec, Tool, the request, the reply
- rpc:       ask(), one request to another service read into a model; NoAnswer, Refused
- build:     rpc.build.start / get: BuildRequest, StartReply, BuildRef (import mycelium_sdk.build)
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
from .prompt import Prompt
from .rpc import NoAnswer, Refused, ask
from .schema import input_schema
from .settings import ServiceSettings, timezone
from .subjects import subject_matches
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
    "ask",
    "NoteType",
    "ServiceSettings",
    "timezone",
]
