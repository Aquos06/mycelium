-- memory index: a searchable copy of the vault. Only the indexer writes here; drop and re-run to rebuild.
-- {schema} is substituted by PostgresIndex (default "memory"). Needs the pg_trgm and vector extensions,
-- which db/init.sql creates.
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.notes (
    id         BIGSERIAL PRIMARY KEY,
    path       TEXT UNIQUE NOT NULL,          -- people/mei.md
    name       TEXT UNIQUE NOT NULL,          -- mei  (the [[link]] target)
    type       TEXT NOT NULL,                 -- self | person | place | project | thing | routine | module
    aliases    TEXT[] NOT NULL DEFAULT '{}',  -- lowercased
    summary    TEXT NOT NULL DEFAULT '',      -- first paragraph
    body_hash  TEXT NOT NULL,                 -- skip unchanged files on re-index
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding  VECTOR(1024)                   -- of name + summary; NULL until computed (M4)
);
CREATE INDEX IF NOT EXISTS notes_name_trgm   ON {schema}.notes USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS notes_aliases_idx ON {schema}.notes USING gin (aliases);

CREATE TABLE IF NOT EXISTS {schema}.links (
    from_note  BIGINT NOT NULL REFERENCES {schema}.notes(id) ON DELETE CASCADE,
    to_name    TEXT NOT NULL,                 -- by name: the target note may not exist yet
    ord        INT NOT NULL DEFAULT 0,        -- order of first appearance in the note
    PRIMARY KEY (from_note, to_name)
);
CREATE INDEX IF NOT EXISTS links_to_name_idx ON {schema}.links (to_name);

CREATE TABLE IF NOT EXISTS {schema}.facts (
    id         BIGSERIAL PRIMARY KEY,
    note_id    BIGINT NOT NULL REFERENCES {schema}.notes(id) ON DELETE CASCADE,
    day        DATE NOT NULL,
    text       TEXT NOT NULL,
    source     TEXT                           -- 'ev:48213' | 'hansen' | 'consolidation' | 'sys'
);
CREATE INDEX IF NOT EXISTS facts_day_idx  ON {schema}.facts (day);
CREATE INDEX IF NOT EXISTS facts_note_idx ON {schema}.facts (note_id);

CREATE TABLE IF NOT EXISTS {schema}.summaries (
    period     TEXT NOT NULL,                 -- day | week | month
    key        TEXT NOT NULL,                 -- 2026-10-14 | 2026-W42 | 2026-10
    path       TEXT NOT NULL,
    text       TEXT NOT NULL,
    links      TEXT[] NOT NULL DEFAULT '{}',
    body_hash  TEXT NOT NULL,
    embedding  VECTOR(1024),
    PRIMARY KEY (period, key)
);
