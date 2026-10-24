"""The core tables (ARCHITECTURE §12), as SQLAlchemy Core Table objects for statements and autogenerate.

    events    the raw event log: everything that crossed the bus; the source of truth for memory
    modules   the supervisor's registry: what is deployed, which manifest, which status
    traces    decision traces: gate / plan / build / notify / feedback, with the user's vote

The tracer writes events and traces, the supervisor writes modules, memory reads events through a
read-only role. The schema itself lives in migrations/core/versions/.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, MetaData, SmallInteger, Table, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

events = Table(
    "events",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("subject", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("is_request", Boolean, nullable=False, server_default=text("false")),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Index("events_ts_idx", text("ts DESC")),
    Index("events_subject_idx", "subject", text("ts DESC")),
    Index("events_source_idx", "source", text("ts DESC")),
)

modules = Table(
    "modules",
    metadata,
    Column("name", Text, primary_key=True),
    Column("version", Text, nullable=False),
    Column("status", Text, nullable=False),  # building | running | stopped | failed | retired
    Column("image", Text),
    Column("manifest", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

traces = Table(
    "traces",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("kind", Text, nullable=False),  # gate | plan | build | notify | feedback | llm | consolidate
    Column("ref", Text),  # event id, module name, build id...
    Column("decision", JSONB, nullable=False),
    Column("feedback", SmallInteger),  # +1 / -1 from the user, null if none
    Index("traces_kind_ts_idx", "kind", text("ts DESC")),
)
