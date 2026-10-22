"""Events are the source of truth. Memory reads them by local day; requests and traces are not memory material."""

from datetime import date
from pathlib import Path

from memory.events import JsonlEvents, is_memory_material

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "events" / "2026-10-14.jsonl"


def test_is_memory_material():
    assert is_memory_material("sense.chat", is_request=False)
    assert is_memory_material("brain.observe", is_request=False)
    assert is_memory_material("mod.expenses.expense.logged", is_request=False)
    assert is_memory_material("sys.module.deployed", is_request=False)
    assert is_memory_material("out.notify", is_request=False)  # what the system said is worth remembering
    assert not is_memory_material("rpc.memory.remember", is_request=True)
    assert not is_memory_material("trace.gate", is_request=False)


async def test_jsonl_events_for_day_in_local_timezone():
    src = JsonlEvents(FIXTURE)
    events = await src.for_day(date(2026, 10, 14), tz="Asia/Taipei")
    ids = [e.id for e in events]
    assert ids == sorted(ids)
    assert 48201 in ids and 48217 in ids
    assert 48205 not in ids  # a request
    assert 48210 not in ids  # a trace
    assert 48216 not in ids  # also a request
    assert 48218 not in ids  # 00:30 the next local day
    assert len(ids) == 14  # 18 lines minus two requests, one trace, one next-day event

    first = events[0]
    assert first.subject == "sense.chat" and first.source == "telegram"
    assert first.payload["text"] == "coffee 85"
    assert first.ts.isoformat() == "2026-10-14T07:52:10+08:00"


async def test_jsonl_events_other_day_is_empty():
    src = JsonlEvents(FIXTURE)
    assert await src.for_day(date(2026, 10, 13), tz="Asia/Taipei") == []
    late = await src.for_day(date(2026, 10, 15), tz="Asia/Taipei")
    assert [e.id for e in late] == [48218]
