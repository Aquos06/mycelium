import pytest

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


def test_decode():
    assert decode(b"") == {}
    assert decode(b'{"a":1}') == {"a": 1}
    assert decode(b"[1,2]") == {"value": [1, 2]}
    assert decode(b"not json") == {"_raw": "not json"}


class FakePool:
    def __init__(self):
        self.rows = []

    async def execute(self, sql, *args):
        self.rows.append(args)


async def test_recorder_inserts_and_skips():
    pool = FakePool()
    r = Recorder(pool)
    assert await r.record("mod.hello.message.counted", b'{"count":1}', False)
    assert not await r.record("_INBOX.xyz", b"{}", False)
    assert pool.rows == [("mod.hello.message.counted", "hello", False, '{"count": 1}')]


async def test_traces_also_land_in_the_traces_table_and_votes_attach_to_plans():
    pool = FakePool()
    r = Recorder(pool)
    await r.record("trace.plan", b'{"id": "p1", "cause": "c1", "reply_id": "s1", "source": "main"}', False)
    assert pool.rows[1] == ("plan", "c1", '{"id": "p1", "cause": "c1", "reply_id": "s1", "source": "main"}')
    await r.record("trace.feedback", b'{"id": "f1", "cause": "c2", "ref": "s1", "vote": -1}', False)
    assert pool.rows[3][0] == "feedback"
    assert pool.rows[4] == (-1, "s1")  # UPDATE traces SET feedback = -1 WHERE reply_id = s1
    await r.record("trace.feedback", b'{"ref": "s1", "answer": "9pm"}', False)
    assert len(pool.rows) == 7  # events + traces rows, no UPDATE for an answer


def test_scaffold_renders_template(tmp_path):
    d = scaffold("widgets", tmp_path)
    m = load_manifest(d / "manifest.yaml")
    assert m.name == "widgets"
    assert "__NAME__" not in (d / "app" / "main.py").read_text()
    assert (d / "CONTRACT.md").exists() and (d / "Dockerfile").exists()


def test_scaffold_rejects_bad_name(tmp_path):
    with pytest.raises(SystemExit):
        scaffold("Bad_Name", tmp_path)
