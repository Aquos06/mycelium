"""Real Postgres: the memory index with pg_trgm and the events reader, against the same fixtures the unit tests use."""

import json
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, text

from memory.events import PostgresEvents
from memory.index import MIGRATIONS, PostgresIndex
from memory.indexer import reindex
from memory.recall import recall
from memory.vault import Vault
from mycelium_sdk.db import CORE_MIGRATIONS, head, make_engine, migrate
from mycelium_sdk.db.core import events
from tests.conftest import DATABASE_URL, needs_pg

pytestmark = [pytest.mark.integration, needs_pg]

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
TODAY = date(2026, 10, 21)


@pytest.fixture
async def schema():
    """Each test gets its own Postgres schema so runs never collide; the core tree provides the extensions."""
    name = f"memtest_{uuid.uuid4().hex[:8]}"
    engine = make_engine(DATABASE_URL, pool_size=2)
    await migrate(engine, CORE_MIGRATIONS)
    yield engine, name
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    await engine.dispose()


async def test_index_round_trip_and_trgm(schema):
    engine, name = schema
    index = PostgresIndex(engine, schema=name)
    await index.ensure_schema()  # memory's Alembic tree into this schema, version table included
    async with engine.connect() as conn:
        version = (await conn.execute(text(f'SELECT version_num FROM "{name}".alembic_version'))).scalar_one()
    assert version == head(MIGRATIONS)  # memory's own head, in this schema's version table

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
    assert ("小美", "mei") in await index.vocabulary()

    again = await reindex(Vault(FIXTURES / "vault"), index)
    assert again.skipped == 7
    await index.ensure_schema()  # idempotent


async def test_recall_against_postgres_matches_the_unit_example(schema):
    engine, name = schema
    index = PostgresIndex(engine, schema=name)
    await index.ensure_schema()
    vault = Vault(FIXTURES / "vault")
    await reindex(vault, index)
    pack = (
        await recall(vault, index, "who did I have dinner with last Wednesday?", today=TODAY, budget=8)
    ).model_dump()
    assert pack["items"][0]["note"] == "summaries/2026/10/14.md"
    assert {i["note"] for i in pack["items"][1:]} >= {"people/mei.md", "places/ramen-place-xinyi.md"}


async def test_postgres_events_for_day(schema):
    engine, _ = schema
    marker = uuid.uuid4().hex[:8]
    rows = [json.loads(line) for line in (FIXTURES / "events" / "2026-10-14.jsonl").read_text().splitlines()]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                insert(events),
                [
                    {
                        "ts": datetime.fromisoformat(r["ts"]),
                        "subject": r["subject"],
                        "source": f"{marker}:{r['source']}",
                        "is_request": r["is_request"],
                        "payload": r["payload"],
                    }
                    for r in rows
                ],
            )
        src = PostgresEvents(engine, source_filter=f"{marker}:%")
        found = await src.for_day(date(2026, 10, 14), tz="Asia/Taipei")
        assert len(found) == 14  # same count the unit test gets from the jsonl
        assert found[0].payload["text"] == "coffee 85"
        assert all(not e.subject.startswith(("rpc.", "trace.")) for e in found)
        assert [e.id for e in found] == sorted(e.id for e in found)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM events WHERE source LIKE :p"), {"p": f"{marker}:%"})
