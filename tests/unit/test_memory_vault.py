"""Vault: markdown notes are the truth. Parsing and rendering must round-trip."""

from datetime import date
from pathlib import Path

import pytest

from memory.vault import Fact, Note, Vault, parse_note, parse_summary, render_note, type_for_path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "vault"


def test_parse_note_frontmatter_summary_links_facts():
    text = (FIXTURES / "people/mei.md").read_text()
    note = parse_note("people/mei.md", text)
    assert note.name == "mei"
    assert note.type == "person"
    assert note.aliases == ["mei", "小美"]  # lowercased
    assert note.summary == "Friend from the climbing gym, lives in [[taipei]]."
    assert note.links == ["taipei", "ramen-place-xinyi"]  # in order of first appearance, no dupes
    assert note.facts == [
        Fact(
            day=date(2026, 10, 14),
            text="dinner at [[ramen-place-xinyi]], she's moving to Tainan in Dec",
            source="ev:48213",
        ),
        Fact(day=date(2026, 9, 2), text='recommended the book "Project Hail Mary"', source="ev:41077"),
    ]


def test_parse_note_without_frontmatter_uses_folder_for_type():
    note = parse_note("places/somewhere.md", "A place.\n\n- 2026-01-02 went there\n")
    assert note.type == "place"
    assert note.aliases == []
    assert note.summary == "A place."
    assert note.facts == [Fact(day=date(2026, 1, 2), text="went there")]


@pytest.mark.parametrize(
    "path,expected",
    [
        ("hansen.md", "self"),
        ("people/mei.md", "person"),
        ("places/x.md", "place"),
        ("projects/x.md", "project"),
        ("modules/x.md", "module"),
        ("things/x.md", "thing"),
        ("routines/x.md", "routine"),
        ("loose.md", "thing"),
    ],
)
def test_type_for_path(path, expected):
    assert type_for_path(path) == expected


def test_render_round_trips():
    original = (FIXTURES / "people/mei.md").read_text()
    note = parse_note("people/mei.md", original)
    rendered = render_note(note)
    assert parse_note("people/mei.md", rendered) == note
    # rendering is canonical: frontmatter, blank line, summary, blank line, facts newest first
    assert rendered.startswith("---\ntype: person\naliases: [mei, 小美]\n---\n")
    assert rendered.rstrip().endswith('- 2026-09-02 recommended the book "Project Hail Mary"  (ev:41077)')


def test_facts_render_newest_first():
    note = Note(
        name="x",
        path="things/x.md",
        type="thing",
        aliases=[],
        summary="X.",
        links=[],
        facts=[Fact(day=date(2026, 1, 1), text="old"), Fact(day=date(2026, 2, 1), text="new", source="hansen")],
    )
    lines = render_note(note).splitlines()
    assert lines[-2:] == ["- 2026-02-01 new  (hansen)", "- 2026-01-01 old"]


@pytest.mark.parametrize(
    "path,period,key",
    [
        ("summaries/2026/10/14.md", "day", "2026-10-14"),
        ("summaries/2026/W42.md", "week", "2026-W42"),
        ("summaries/2026/10.md", "month", "2026-10"),
    ],
)
def test_parse_summary_period_and_key(path, period, key):
    s = parse_summary(path, "Something with [[mei]].\n")
    assert (s.period, s.key) == (period, key)
    assert s.links == ["mei"]
    assert s.text == "Something with [[mei]]."


def test_parse_summary_rejects_unknown_path():
    with pytest.raises(ValueError):
        parse_summary("summaries/nope.md", "x")


def test_vault_lists_notes_and_summaries_separately():
    vault = Vault(FIXTURES)
    notes = {n.name for n in vault.notes()}
    assert notes == {"hansen", "mei", "ramen-place-xinyi", "mycelium", "expenses"}
    summaries = {(s.period, s.key) for s in vault.summaries()}
    assert summaries == {("day", "2026-10-14"), ("week", "2026-W42")}


def test_vault_path_for_type():
    vault = Vault(FIXTURES)
    assert vault.path_for("mei", "person") == "people/mei.md"
    assert vault.path_for("hansen", "self") == "hansen.md"
    assert vault.path_for("expenses", "module") == "modules/expenses.md"
    assert vault.path_for("bike", "thing") == "things/bike.md"


def test_vault_write_then_read(tmp_path):
    vault = Vault(tmp_path)
    note = Note(
        name="bike",
        path="things/bike.md",
        type="thing",
        aliases=["my bike"],
        summary="Grey gravel bike.",
        links=[],
        facts=[Fact(day=date(2026, 10, 1), text="new chain", source="hansen")],
    )
    vault.write(note)
    assert (tmp_path / "things/bike.md").exists()
    assert vault.read("things/bike.md") == note
    assert vault.exists("things/bike.md") and not vault.exists("things/car.md")


def test_vault_rejects_paths_outside_root(tmp_path):
    vault = Vault(tmp_path)
    with pytest.raises(ValueError):
        vault.read("../etc/passwd")
    with pytest.raises(ValueError):
        vault.path_for("../x", "thing")
