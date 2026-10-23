"""Real Postgres: the memory index with pg_trgm and the events reader, against the same fixtures the unit tests use."""

import json
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest

from memory.events import PostgresEvents
from memory.index import PostgresIndex
from memory.indexer import reindex
from memory.recall import recall
from memory.vault import Vault
from tests.conftest import DATABASE_URL, needs_pg

pytestmark = [pytest.mark.integration, needs_pg]

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
TODAY = date(2026, 10, 21)


@pytest.fixture
async def schema():
    """Each test gets its own Postgres schema so runs never collide."""
    import asyncpg

    name = f"memtest_{uuid.uuid4().hex[:8]}"
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    await pool.execute((REPO / "db/init.sql").read_text())
    yield pool, name
    await pool.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")
    await pool.close()


async def test_index_round_trip_and_trgm(schema):
    pool, name = schema
    index = PostgresIndex(pool, schema=name)
    await index.ensure_schema()
    stats = await reindex(Vault(FIXTURES / "vault"), index)
    assert stats.notes == 5 and stats.summaries == 2

    assert (await index.get("MEI")).path == "people/mei.md"
    assert [r.name for r in await index.by_alias("小美")] == ["mei"]
    fuzzy = await index.fuzzy("meii", limit=3)
    assert fuzzy[0][0].name == "mei" and 0.45 <= fuzzy[0][1] <= 0.55  # pg_trgm similarity, the real one
    assert {r.name for r in await index.backlinks("mei")} == {"ramen-place-xinyi"}
    facts = await index.facts(day=date(2026, 10, 14))
    assert {f.note for f in facts} == {"hansen", "mei", "ramen-place-xinyi", "expenses"}
    assert (await index.summary("week", "2026-W42")).links == ["mei", "mycelium"]

    again = await reindex(Vault(FIXTURES / "vault"), index)
    assert again.skipped == 7


async def test_recall_against_postgres_matches_the_unit_example(schema):
    pool, name = schema
    index = PostgresIndex(pool, schema=name)
    await index.ensure_schema()
    vault = Vault(FIXTURES / "vault")
    await reindex(vault, index)
    pack = (
        await recall(vault, index, "who did I have dinner with last Wednesday?", today=TODAY, budget=8)
    ).model_dump()
    assert pack["items"][0]["note"] == "summaries/2026/10/14.md"
    assert {i["note"] for i in pack["items"][1:]} >= {"people/mei.md", "places/ramen-place-xinyi.md"}


async def test_postgres_events_for_day(schema):
    pool, _ = schema
    marker = uuid.uuid4().hex[:8]
    rows = [json.loads(line) for line in (FIXTURES / "events" / "2026-10-14.jsonl").read_text().splitlines()]
    try:
        for r in rows:
            await pool.execute(
                "INSERT INTO events (ts, subject, source, is_request, payload) VALUES ($1, $2, $3, $4, $5::jsonb)",
                datetime.fromisoformat(r["ts"]),
                r["subject"],
                f"{marker}:{r['source']}",
                r["is_request"],
                json.dumps(r["payload"]),
            )
        src = PostgresEvents(pool, source_filter=f"{marker}:%")
        events = await src.for_day(date(2026, 10, 14), tz="Asia/Taipei")
        assert len(events) == 14  # same count the unit test gets from the jsonl
        assert events[0].payload["text"] == "coffee 85"
        assert all(not e.subject.startswith(("rpc.", "trace.")) for e in events)
        assert [e.id for e in events] == sorted(e.id for e in events)
    finally:
        await pool.execute("DELETE FROM events WHERE source LIKE $1", f"{marker}:%")
