-- mycelium core schema (runs once on first Postgres start)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Raw event log: everything that crossed the bus. Source of truth for memory.
CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    subject     TEXT        NOT NULL,
    source      TEXT        NOT NULL,
    is_request  BOOLEAN     NOT NULL DEFAULT false,
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS events_ts_idx      ON events (ts DESC);
CREATE INDEX IF NOT EXISTS events_subject_idx ON events (subject, ts DESC);
CREATE INDEX IF NOT EXISTS events_source_idx  ON events (source, ts DESC);

-- Module registry: what the supervisor has deployed.
CREATE TABLE IF NOT EXISTS modules (
    name        TEXT PRIMARY KEY,
    version     TEXT        NOT NULL,
    status      TEXT        NOT NULL,      -- building | running | stopped | failed | retired
    image       TEXT,
    manifest    JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Decision traces: every gate/plan/build decision with its inputs, for /why and evals.
CREATE TABLE IF NOT EXISTS traces (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT        NOT NULL,      -- gate | plan | build | notify | feedback
    ref         TEXT,                      -- event id, module name, build id...
    decision    JSONB       NOT NULL,
    feedback    SMALLINT                   -- +1 / -1 from the user, null if none
);
CREATE INDEX IF NOT EXISTS traces_kind_ts_idx ON traces (kind, ts DESC);
