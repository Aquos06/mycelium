"""Every shape memory speaks, in one place (same layout as the gateway's schemas/).

vault.py        the files: Note, Fact, Summary, NoteType, NAME_RE
index.py        the searchable copy: NoteRecord, FactRecord, SummaryRecord, IndexStats
events.py       the raw log: Event
rpc.py          rpc.memory.* requests and replies: RememberRequest, LookupRequest, RecallRequest, ConsolidateRequest, ...
recall.py       the lookup ladder's Match and the RecallPack the planner reads
consolidate.py  the nightly job: DayDigest (what the model returns), ConsolidationReport, ConsolidateTrace
"""

from .consolidate import (
    ConsolidateTrace,
    ConsolidationReport,
    DayDigest,
    DigestFact,
    ModelRequest,
    StateUpdate,
)
from .events import Event
from .index import FactRecord, IndexStats, NoteRecord, SummaryRecord
from .recall import Match, RecallBudget, RecallItem, RecallPack, RecallUsed
from .rpc import (
    ConsolidateRequest,
    FactIn,
    LookupMatch,
    LookupReply,
    LookupRequest,
    RecallRequest,
    RememberReply,
    RememberRequest,
)
from .vault import NAME_RE, Fact, Note, NoteType, Summary

__all__ = [
    "NAME_RE",
    "Fact",
    "Note",
    "NoteType",
    "Summary",
    "FactRecord",
    "IndexStats",
    "NoteRecord",
    "SummaryRecord",
    "Event",
    "ConsolidateRequest",
    "FactIn",
    "LookupMatch",
    "LookupReply",
    "LookupRequest",
    "RecallRequest",
    "RememberReply",
    "RememberRequest",
    "Match",
    "RecallBudget",
    "RecallItem",
    "RecallPack",
    "RecallUsed",
    "ConsolidateTrace",
    "ConsolidationReport",
    "DayDigest",
    "DigestFact",
    "ModelRequest",
    "StateUpdate",
]
