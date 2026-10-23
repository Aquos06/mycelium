# Memory

How mycelium remembers. For where memory sits in the system, see [ARCHITECTURE.md](ARCHITECTURE.md)
§6; for why it is structure-first, see [VISION.md](VISION.md).

The one-line version: **the raw event log is the truth, a folder of markdown notes is the curated
memory, Postgres holds a searchable copy of those notes, and recall is a small program that opens
the right notes rather than a vector search.**

Memory is fed by everything on the bus (chat, module observations, later mail and calendar), not
only by conversation, and the notes are files Hansen can open and edit.

## The four layers

```
events (Postgres, owned by the tracer)     source of truth, already exists
   ↓ nightly consolidation + explicit "remember"
vault (markdown files, a git repo)         one note per entity, [[links]], human-editable
   ↓ re-index any time
index (Postgres, mycelium_memory)          names, aliases, types, links, facts, embeddings
   ↓ at question time
recall pack                                the few notes and summaries the planner gets to see
```

Each layer can be rebuilt from the one above it. Delete the index and re-run the indexer; delete a
summary and re-run consolidation for that day.

## 1. The vault

A folder of markdown files on memory's volume, initialised as a git repo (free history, diff and
rollback of memory; opens in Obsidian).

```
vault/
  hansen.md                    the profile: who Hansen is, preferences, routines
  people/mei.md
  places/ramen-place-xinyi.md
  projects/mycelium.md
  modules/expenses.md          one per deployed module, written automatically
  summaries/2026/10/14.md      day
  summaries/2026/W42.md        week
  summaries/2026/10.md         month
```

One note per entity: `self`, `person`, `place`, `project`, `thing`, `routine`, `module`. The file
name is the note's name and the `[[link]]` target.

```markdown
---
type: person
aliases: [Mei, 小美]
---
Friend from the climbing gym, lives in [[taipei]].

- 2026-10-14 dinner at [[ramen-place-xinyi]], she's moving to Tainan in Dec  (ev:48213)
- 2026-09-02 recommended the book "Project Hail Mary"  (ev:41077)
```

Three parts, each with a job:

- **Frontmatter**: type and aliases (every name this entity goes by, in any language).
- **First paragraph**: the current state, one or two sentences. Consolidation rewrites it when the
  dated bullets below make it stale.
- **Dated bullets**: facts, newest first, each ending with its provenance: `ev:<id>` is the event
  that caused it, `hansen` means he said so, `consolidation` means the nightly job inferred it. Every
  fact can be traced to what caused it.

Summaries follow the same idea at the level of a day, a week or a month, and link to the notes they
mention.

**Memory knows where a fact lives; modules own exact data.** `modules/expenses.md` says "spending is
tracked by `expenses`, ask `rpc.mod.expenses.summary`". It never copies the expenses. Otherwise the
same numbers live in two places and drift apart.

## 2. The index

Postgres database `mycelium_memory`, memory's own (ARCHITECTURE §12). It holds a **searchable copy of
the vault, not a second place where knowledge lives.**

### Why copy markdown into tables at all

Markdown is for reading, Postgres is for finding. A note is the right shape for Hansen and the LLM
to read, but some questions cannot be answered by reading one file:

| Question | On files | With the index |
|---|---|---|
| everything that happened on 2026-10-14, across all notes | open every file, parse every bullet | `SELECT … FROM facts WHERE day = '2026-10-14'` |
| which notes link *to* mei (backlinks) | grep every file for `[[mei]]` | `SELECT from_note FROM links WHERE to_name = 'mei'` |
| "Meii" → mei (typo, nickname) | impossible with grep | `pg_trgm` similarity |
| "that ramen place" (vague) | impossible with grep | embedding search |

With 50 notes, grepping is fine. With 5,000 notes and three years of daily summaries it is not, and
the fuzzy and embedding lookups need a database regardless.

### Derived, never hand-maintained

Only one program writes the tables: the indexer. Nobody runs `INSERT INTO facts` by hand.

```
writers of markdown                        the only writer of tables
  nightly consolidation  ─┐                  ┌─ indexer: watch vault → parse → upsert
  rpc.memory.remember    ─┼─► vault/*.md ───►┤          (also computes embeddings)
  module note on deploy  ─┤                  └─► notes · links · facts · summaries
  Hansen, in Obsidian    ─┘                                 │
                                                            ▼
                                                 readers: recall (lookup ladder, backlinks,
                                                 facts by day, summaries by key)
```

Edit a note in Obsidian and the indexer updates the rows. If the tables are ever wrong, drop them
and re-run the indexer; nothing is lost. The indexer maps each part of a file to a table:
frontmatter → columns, first paragraph → `summary`, every `[[x]]` → a `links` row, every bullet that
starts with a date → a `facts` row.

### Schema

```sql
CREATE TABLE notes (
    id         BIGSERIAL PRIMARY KEY,
    path       TEXT UNIQUE NOT NULL,          -- people/mei.md
    name       TEXT UNIQUE NOT NULL,          -- mei  (the [[link]] target)
    type       TEXT NOT NULL,                 -- self | person | place | project | thing | routine | module
    aliases    TEXT[] NOT NULL DEFAULT '{}',  -- lowercased
    summary    TEXT NOT NULL DEFAULT '',      -- first paragraph
    body_hash  TEXT NOT NULL,                 -- skip unchanged files on re-index
    updated_at TIMESTAMPTZ NOT NULL,
    embedding  VECTOR(1024)                   -- of name + summary; NULL until computed
);
CREATE INDEX notes_name_trgm    ON notes USING gin (name gin_trgm_ops);
CREATE INDEX notes_aliases_idx  ON notes USING gin (aliases);
CREATE INDEX notes_embedding    ON notes USING hnsw (embedding vector_cosine_ops);

CREATE TABLE links (
    from_note  BIGINT REFERENCES notes(id) ON DELETE CASCADE,
    to_name    TEXT NOT NULL,                 -- by name: the target note may not exist yet
    PRIMARY KEY (from_note, to_name)
);

CREATE TABLE facts (
    id         BIGSERIAL PRIMARY KEY,
    note_id    BIGINT REFERENCES notes(id) ON DELETE CASCADE,
    day        DATE NOT NULL,
    text       TEXT NOT NULL,
    source     TEXT                           -- 'ev:48213' | 'hansen' | 'consolidation'
);
CREATE INDEX facts_day_idx ON facts (day);

CREATE TABLE summaries (
    period     TEXT NOT NULL,                 -- day | week | month
    key        TEXT NOT NULL,                 -- 2026-10-14 | 2026-W42 | 2026-10
    path       TEXT NOT NULL,
    text       TEXT NOT NULL,
    embedding  VECTOR(1024),
    PRIMARY KEY (period, key)
);
```

`events` is **not** in this database. It lives in `mycelium_tracer`; memory reads it through a
read-only role.

The honest minimum for v0 is `notes` and `links`. `facts` and `summaries` are optimizations (recall
can read `summaries/2026/10/14.md` from disk), but the indexer parses those bullets anyway and the
cost is a few lines, so they are created from the start.

### Example rows

`notes`

| id | path | name | type | aliases | summary |
|---|---|---|---|---|---|
| 1 | `hansen.md` | hansen | self | `{hansen, 我}` | Lives in Taipei, works on [[mycelium]], climbs twice a week. |
| 2 | `people/mei.md` | mei | person | `{mei, 小美}` | Friend from the climbing gym, lives in [[taipei]]. |
| 3 | `places/ramen-place-xinyi.md` | ramen-place-xinyi | place | `{menya xinyi, 那家拉麵}` | Ramen shop near Xinyi Anhe station; usual order is the shoyu. |
| 4 | `modules/expenses.md` | expenses | module | `{spending, 支出}` | Tracks spending. Exact numbers: ask `rpc.mod.expenses.summary`. |

`links`

| from_note | to_name |
|---|---|
| 2 | taipei |
| 2 | ramen-place-xinyi |
| 1 | mycelium |

`facts`

| note_id | day | text | source |
|---|---|---|---|
| 2 | 2026-10-14 | dinner at [[ramen-place-xinyi]], she's moving to Tainan in Dec | ev:48213 |
| 2 | 2026-09-02 | recommended the book "Project Hail Mary" | ev:41077 |

`summaries`

| period | key | text |
|---|---|---|
| day | 2026-10-14 | Dinner with [[mei]] at [[ramen-place-xinyi]], 350 TWD. Afternoon on [[mycelium]] docs. Slept 23:40. |
| week | 2026-W42 | Three climbing sessions. Spending 4,120 TWD, mostly food. [[mei]] moving to Tainan in December. |

## 3. Writing memory

Two paths write the vault; both end with the indexer catching up.

**Explicit.** Hansen says "remember that Mei is moving to Tainan in December". The planner calls
`rpc.memory.remember {text, source}`. One LLM call through the gateway extracts entities and facts;
memory upserts the notes and appends dated bullets with `hansen` or the event id as provenance.

**Nightly consolidation.** For yesterday:

```sql
-- mycelium_tracer, read-only role
SELECT id, ts, subject, payload
FROM events
WHERE ts >= '2026-10-14' AND ts < '2026-10-15'
  AND (subject LIKE 'sense.%' OR subject = 'brain.observe' OR subject LIKE 'mod.%')
ORDER BY ts;
```

One LLM pass over that writes `summaries/2026/10/14.md`, appends notable facts to the notes they
belong to (each with its `ev:<id>`), creates notes for new entities, and adds links. Weekly and
monthly rollups are written from the days when the period closes. When a note's dated history grows
long, consolidation rewrites its first paragraph (current state) and keeps the bullets.

**Built (M3, `services/memory/consolidate.py`).** The pass is one forced tool call, `write_day`, on
the gateway's `consolidate` slot (a cheap model; `providers.yaml`). The prompt carries the day's
events, one line each with its id, and the known notes with their aliases; the answer is validated
as `DayDigest` (summary, facts with the event ids they come from, state updates), and an invalid
answer goes back to the model once with the field errors. It runs for yesterday at
`MEMORY_CONSOLIDATE_AT` (03:30 local by default) and for any day on `rpc.memory.consolidate {day}`,
`mctl consolidate 2026-10-14`. Idempotent per day: the summary is rewritten, a fact is skipped when
the note already has one from the same event or the same line on that day, so a prompt change can be
replayed over past days. A fact whose event ids the model got wrong is kept with `consolidation` as
provenance. The prompt lists the facts already recorded for that day (from `remember` during the day,
or an earlier run), so the model adds only what is new, and it is told that the assistant's own
`out.*` replies are not facts about anyone. After the model answers, ordinary code wraps known names
and aliases it left bare in `[[slug|name]]`, so the day summary links like the rest of the vault and
recall can hop from it. Every run publishes `trace.consolidate` with counts and cost. Rollups come
with M4.

First live run (2026-10-23, a reasoning model on vLLM): a day of 44 events took one call of about
25 s, the summary came back in English with links, and recall hopped from it to the notes it named.

**Modules.** On `sys.module.deployed`, memory writes or updates `modules/<name>.md` from the
manifest: purpose, the requests it answers, and the rule that exact data is fetched from the module.

## 4. Recall

`rpc.memory.recall {query, budget}` answers: which notes should the planner get to read for this
question? It is a small program, not a vector search, because for one person's life the questions
are mostly about **who, when and how things connect**, and names, dates and links answer those
exactly and for free. Vector search is good at vague questions and bad at exact ones, so it gets
the vague ones only.

### The lookup ladder

How a name in a question becomes a note. Each step runs only if the previous one found nothing.

```sql
-- question: "what did 小美 say about Tainan?"

-- 1. exact name
SELECT id FROM notes WHERE name = '小美';                        -- nothing

-- 2. alias
SELECT id FROM notes WHERE '小美' = ANY(aliases);                -- → 2 (mei). Stop.

-- 3. fuzzy (typos, spelling variants), e.g. "Meii"
SELECT id, similarity(name, 'meii') AS s
FROM notes WHERE name % 'meii' ORDER BY s DESC LIMIT 3;         -- → mei, 0.6

-- 4. embedding, for questions with no name at all, e.g. "that ramen place in Xinyi"
SELECT id FROM notes ORDER BY embedding <=> $query_vec LIMIT 5; -- → ramen-place-xinyi
```

Most lookups stop at step 1 or 2 with one cheap query. Embeddings exist for the vague remainder.

### The steps

1. **Dates.** "last Tuesday" → `2026-10-14` (a date parser, no model) → open that day's summary.
2. **Names.** Run the ladder on the names in the question → open those notes.
3. **Links.** If an opened note or summary links to another and the budget allows, open it (one hop).
4. **Fallback.** If 1–2 found nothing, embedding search over notes and summaries.
5. **Pack.** Return a few `{note, excerpt, why}` items plus today's and yesterday's summaries.

`budget` caps the pack (for example 8 notes) so it stays small enough for the planner. The pack is
stored in the decision trace, so "why did you say that?" can show which notes were opened and why.
The steps are ordinary code: the same question opens the same notes, and there are tests for it.

### Example

*"who did I have dinner with last Tuesday?"*, asked on 2026-10-21.

| Step | Query | Result |
|---|---|---|
| dates | last Tuesday → `2026-10-14` → `SELECT text FROM summaries WHERE period='day' AND key='2026-10-14'` | the day summary, mentions `[[mei]]`, `[[ramen-place-xinyi]]` |
| names | none in the question | — |
| links | `SELECT * FROM notes WHERE name IN ('mei','ramen-place-xinyi')` | 2 notes |
| facts | `SELECT text FROM facts WHERE note_id = 2 AND day = '2026-10-14'` | "dinner at ramen-place-xinyi, she's moving to Tainan…" |
| fallback | not needed | — |

The pack the planner receives, and the trace stores:

```json
{
  "query": "who did I have dinner with last Tuesday?",
  "items": [
    {"note": "summaries/2026/10/14.md", "why": "last Tuesday = 2026-10-14",
     "excerpt": "Dinner with [[mei]] at [[ramen-place-xinyi]], 350 TWD."},
    {"note": "people/mei.md", "why": "linked from the day summary",
     "excerpt": "2026-10-14 dinner at [[ramen-place-xinyi]], she's moving to Tainan in Dec"},
    {"note": "places/ramen-place-xinyi.md", "why": "linked from the day summary",
     "excerpt": "Ramen shop near Xinyi Anhe station; usual order is the shoyu."}
  ],
  "budget": {"notes_opened": 3, "max": 8}
}
```

No embedding was used. It would have been, had the question been "that place with the good shoyu".

### Where a decision model fits

Recall has two kinds of work. **Finding candidates** (dates, names, links) needs no model: it is
exact, free and testable, and a model that returns choices rather than text could not do it anyway.
**Deciding among candidates** is score-shaped, and that is what the `rerank` slot (ARCHITECTURE §11)
is for:

| Decision | Input | Returns |
|---|---|---|
| does this message need memory, and which kind? | message + snapshot | none / entity / time / module-data, with probability |
| which of these 20 candidates matter? | question + 20 note summaries | a relevance score per candidate |
| "Mei" matches two notes; which one? | question + both summaries | a choice with confidence; low confidence → open both |

The first decision rides on the gate call Main already makes for every event (one more field in the
same parallel call), so recall only runs when it is useful.

Providers for the slot: **Jev** (cloud, scores in ~100 ms) and a **local cross-encoder reranker**
(`bge-reranker-v2-m3` or similar on GPU 1, a few milliseconds). Note summaries are the most personal
text the system has, so for recall the local reranker is `active` and Jev is `shadow`, the reverse of
the gate. Recall v0 ships without the slot at all; it goes in when the logs show candidates exceeding
the budget often or ambiguity cases piling up.

## 5. How Main uses memory

Planner context = policy + state snapshot + **recall pack** + the last N turns of the thread.
"Small context for deciding, big context for thinking": the gate never sees the vault; the planner
sees only the pack.

The thread itself (working memory: what we are talking about right now) lives in Main's NATS KV, not
in the memory service. Long-term goes to the vault.

## 6. Frameworks

None for v0. Mem0, Letta and LightRAG assume embedding-first retrieval, the opposite of this design,
and v0 is a few hundred lines. Graphiti (temporal knowledge graph) is the one to revisit if following
links proves too weak for "how are these connected" questions.

## 7. Evaluation

A small set of questions with expected answers ("who did I have dinner with last Tuesday?" →
"Mei"), run after every change to consolidation or recall. Plus the recall pack in every trace, so a
wrong answer can be traced to the wrong note being opened, or the right one not being written.

## Build order

`services/memory/` has the same shape as the gateway: `schemas/` holds every pydantic shape (vault
notes and facts, index records, events, `rpc.memory.*` requests and replies, the recall pack, the
consolidation digest and report); `index/` and `events/` are the two pluggable backends (in-memory
and Postgres; jsonl and Postgres); `vault.py`, `indexer.py`, `recall.py`, `consolidate.py` and
`schedule.py` are the logic; `service.py` the rpc handlers; `settings.py` the environment.

| Step | What you get |
|---|---|
| **M1** (done) vault format, indexer, `notes` + `links` + `facts` + `summaries`, lookup ladder (exact, alias, trgm), `remember` / `lookup` / `recall` / `reindex`, module notes on deploy, `mctl remember` / `lookup` / `recall` | memory usable from the CLI; pure code, no model needed. `services/memory/`, tests in `tests/unit/test_memory_*.py` and `tests/integration/test_memory_pg.py`, fixtures in `tests/fixtures/` |
| **M2** (done) Main v0: gateway (Claude or a local OpenAI-compatible model, `services/gateway/`), thread in NATS KV, planner with the recall pack and the `remember` / `recall` / `ask_module` / `ask` tools (`services/main/`), `trace.plan` per answer, Telegram in and out with `out.ask` buttons, `mctl chat` | the chatbot core with memory, end to end. Tests in `tests/unit/test_gateway.py`, `test_main.py`, `test_telegram.py` |
| **M3** (done) nightly consolidation (`services/memory/consolidate.py`, `schedule.py`): one forced tool call on the `consolidate` slot writes the day summary, dated facts with `ev:<id>`, new notes and state updates; `rpc.memory.consolidate` / `mctl consolidate` replay any day; `trace.consolidate` per run | memory that grows without being told to. Tests in `tests/unit/test_memory_consolidate.py` |
| **M4** embeddings (local on GPU 1, or an API to start), week and month rollups, the `rerank` slot | fuzzy recall |
| **M5** the eval set | you know when memory gets worse |
