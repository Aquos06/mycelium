"""Every shape memory speaks, in one place (same layout as the gateway's schemas/).

vault.py        the files: Note, Fact, Summary, NoteType, NAME_RE
index.py        the searchable copy: NoteRecord, FactRecord, SummaryRecord, IndexStats
events.py       the raw log: Event
embed.py        embeddings: EmbedTarget, Neighbour, EmbedCall, EmbedSweepReport, EmbedTrace
periods.py      week and month keys, paths and days
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
    PeriodDigest,
    RollupReport,
    RollupTrace,
    StateUpdate,
)
from .embed import EmbedCall, EmbedSweepReport, EmbedTarget, EmbedTrace, Neighbour, embedding_text
from .events import Event
from .index import FactRecord, IndexStats, NoteRecord, SummaryRecord
from .periods import Period, month_key, parse_period_key, period_days, period_path, periods_closed_by, week_key
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
    RollupRequest,
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
    "Period",
    "month_key",
    "parse_period_key",
    "period_days",
    "period_path",
    "periods_closed_by",
    "week_key",
    "Event",
    "EmbedCall",
    "EmbedSweepReport",
    "EmbedTarget",
    "EmbedTrace",
    "Neighbour",
    "embedding_text",
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
    "PeriodDigest",
    "RollupReport",
    "RollupTrace",
    "RollupRequest",
    "StateUpdate",
]
