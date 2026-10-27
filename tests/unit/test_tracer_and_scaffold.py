import pytest
from sqlalchemy.dialects import postgresql

from mycelium_sdk import load_manifest
from new_module import scaffold
from tracer import Recorder, decode, should_record, source_of


@pytest.mark.parametrize(
    "subject,data,expected",
    [
        ("mod.hello.message.counted", {}, "hello"),
        ("rpc.mod.hello.stats", {}, "hello"),
        ("rpc.sys.deploy", {}, "sys"),
        ("sense.chat", {}, "sense"),
        ("brain.observe", {"source": "expenses"}, "expenses"),
    ],
)
def test_source_of(subject, data, expected):
    assert source_of(subject, data) == expected


def test_should_record():
    assert should_record("sense.chat")
    assert not should_record("_INBOX.abc")
    assert not should_record("$JS.API.STREAM.INFO")
    assert not should_record("stream.llm")  # a reply as it is written: live only, the reply itself lands on out.say


def test_decode():
    assert decode(b"") == {}
    assert decode(b'{"a":1}') == {"a": 1}
    assert decode(b"[1,2]") == {"value": [1, 2]}
    assert decode(b"not json") == {"_raw": "not json"}


class FakeEngine:
    """Stands in for the async engine: compiles each statement for Postgres and records (table, params)."""

    def __init__(self):
        self.rows = []

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.rows.append((stmt.table.name, stmt.compile(dialect=postgresql.dialect()).params))


async def test_recorder_inserts_and_skips():
    engine = FakeEngine()
    r = Recorder(engine)
    assert await r.record("mod.hello.message.counted", b'{"count":1}', False)
    assert not await r.record("_INBOX.xyz", b"{}", False)
    assert engine.rows == [
        (
            "events",
            {"subject": "mod.hello.message.counted", "source": "hello", "is_request": False, "payload": {"count": 1}},
        )
    ]


async def test_traces_also_land_in_the_traces_table_and_votes_attach_to_plans():
    engine = FakeEngine()
    r = Recorder(engine)
    await r.record("trace.plan", b'{"id": "p1", "cause": "c1", "reply_id": "s1", "source": "main"}', False)
    table, params = engine.rows[1]
    assert table == "traces" and params["kind"] == "plan" and params["ref"] == "c1"
    assert params["decision"]["reply_id"] == "s1"
    await r.record("trace.feedback", b'{"id": "f1", "cause": "c2", "ref": "s1", "vote": -1}', False)
    assert engine.rows[3][1]["kind"] == "feedback"
    table, params = engine.rows[4]  # UPDATE traces SET feedback = -1 WHERE kind = 'plan' AND reply_id = 's1'
    assert table == "traces" and params["feedback"] == -1 and {"plan", "s1"} <= set(params.values())
    await r.record("trace.feedback", b'{"ref": "s1", "answer": "9pm"}', False)
    assert len(engine.rows) == 7  # events + traces rows, no UPDATE for an answer


def test_scaffold_renders_template(tmp_path):
    d = scaffold("widgets", tmp_path)
    m = load_manifest(d / "manifest.yaml")
    assert m.name == "widgets"
    assert "__NAME__" not in (d / "app" / "main.py").read_text()
    assert (d / "CONTRACT.md").exists() and (d / "Dockerfile").exists()


def test_scaffold_rejects_bad_name(tmp_path):
    with pytest.raises(SystemExit):
        scaffold("Bad_Name", tmp_path)
