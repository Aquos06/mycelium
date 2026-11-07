"""The builder before anything runs: the folder it scaffolds and tidies, the manifest it pins, the static
rules, and GROWN_DIR as a git repo."""

import pytest
import yaml

from builder.checks import check_files, check_python, pin_manifest, relative_names
from builder.repo import GrownRepo
from builder.workspace import CONTRACT, PROTECTED, SPEC, Workspace, coder_may_write, scaffold, write_file
from tests.unit.builder_fakes import GOOD, TEMPLATE, git

# ---- the folder ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel, ok",
    [
        ("manifest.yaml", True),
        ("requirements.txt", False),  # the builder's: standard library only, and the Dockerfile copies it
        ("app/main.py", True),
        ("app/store.py", True),
        ("tests/test_notes.py", True),
        ("app/__init__.py", False),  # the template's
        ("tests/conftest.py", False),
        (CONTRACT, False),  # the builder's own test
        ("tests/helpers.py", False),  # tests are test_*.py
        ("app/sub/x.py", False),  # flat
        ("Dockerfile", False),
        ("CONTRACT.md", False),
        ("SPEC.md", False),
        ("../escape.py", False),
        ("app/Main.py", False),
        ("run.sh", False),
    ],
)
def test_what_a_coder_may_write(rel, ok):
    assert coder_may_write(rel) is ok


def test_write_file_refuses_a_path_a_coder_does_not_own(tmp_path):
    with pytest.raises(ValueError, match="not yours"):
        write_file(tmp_path, "Dockerfile", "FROM evil")
    write_file(tmp_path, "app/main.py", "x = 1\n")
    assert (tmp_path / "app" / "main.py").read_text() == "x = 1\n"


def test_scaffold_refuses_a_bad_name_and_an_existing_folder(tmp_path):
    with pytest.raises(ValueError):
        scaffold("Bad_Name", tmp_path, TEMPLATE)
    scaffold("notes", tmp_path, TEMPLATE)
    with pytest.raises(FileExistsError):
        scaffold("notes", tmp_path, TEMPLATE)


def test_start_scaffolds_staging_with_the_spec_and_replaces_an_old_one(tmp_path):
    ws = Workspace(tmp_path, TEMPLATE)
    d = ws.start("notes", "spec one\n")
    (d / "app" / "leftover.py").write_text("x")
    d = ws.start("notes", "spec two\n")
    assert d == tmp_path / ".staging" / "notes"
    assert (d / SPEC).read_text() == "spec two\n"
    assert not (d / "app" / "leftover.py").exists()
    assert "name: notes" in (d / "manifest.yaml").read_text()


def test_tidy_puts_the_builders_files_back_and_removes_strays(tmp_path):
    ws = Workspace(tmp_path, TEMPLATE)
    d = ws.start("notes", "the spec\n")
    for rel, text in GOOD.items():
        write_file(d, rel, text)
    (d / "Dockerfile").write_text("FROM evil\n")
    (d / "requirements.txt").unlink()  # an agent deleted it: the Dockerfile copies it, so it comes back
    (d / "CONTRACT.md").write_text("no rules\n")
    (d / "app" / "__init__.py").write_text("import os\n")
    (d / SPEC).write_text("a different spec\n")
    (d / "run.sh").write_text("curl evil\n")
    (d / "data").mkdir()
    (d / "data" / "x.db").write_text("")
    (d / "app" / "link.py").symlink_to("/etc/hosts")
    (d / "app" / "__pycache__").mkdir()
    (d / "app" / "__pycache__" / "main.pyc").write_text("")

    removed = ws.tidy("notes", "the spec\n")

    assert sorted(removed) == ["app/link.py", "data/", "run.sh"]
    for rel in PROTECTED:
        assert (d / rel).read_text() == (TEMPLATE / rel).read_text().replace("__NAME__", "notes")
    assert (d / SPEC).read_text() == "the spec\n"
    assert "Written by the builder" in (d / CONTRACT).read_text()
    assert (d / "app" / "main.py").read_text() == GOOD["app/main.py"]
    assert not (d / "app" / "__pycache__").exists()
    assert set(ws.files("notes")) >= {"manifest.yaml", "app/main.py", "tests/test_notes.py", CONTRACT}


def test_promote_moves_staging_and_never_overwrites(tmp_path):
    ws = Workspace(tmp_path, TEMPLATE)
    ws.start("notes", "s\n")
    assert ws.promote("notes") == tmp_path / "notes"
    assert ws.exists("notes") and not ws.staging("notes").exists()
    ws.start("notes", "s\n")
    with pytest.raises(FileExistsError):
        ws.promote("notes")


# ---- the manifest -------------------------------------------------------------------------------------


def test_pin_manifest_sets_the_builders_fields(tmp_path):
    (tmp_path / "manifest.yaml").write_text(GOOD["manifest.yaml"] + "name: other\nversion: 9.9.9\n")
    manifest, problems = pin_manifest(tmp_path, "notes", "0.1.0")
    assert problems == []
    assert manifest.name == "notes" and manifest.version == "0.1.0"
    assert not manifest.permissions.network and not manifest.permissions.actuation  # the coder asked for both
    assert yaml.safe_load((tmp_path / "manifest.yaml").read_text())["permissions"] == {
        "network": False,
        "actuation": False,
    }


@pytest.mark.parametrize(
    "text, expect",
    [
        ("purpose: [", "not valid YAML"),
        ("- a list\n", "must be a mapping"),
        ("purpose: short\n", "purpose"),
        ("purpose: Keeps notes for the user.\nemits: [mod.notes.kept]\n", "write 'kept'"),
        ("purpose: Keeps notes for the user.\nrequests: [rpc.mod.notes.last]\n", "write 'last'"),
        ("purpose: Keeps notes for the user.\nsubscribes: [rpc.sys.deploy]\n", "may not subscribe"),
        ("purpose: Keeps notes for the user.\nrequests: [last]\n", "not described: last"),  # Main would guess
        (  # a page that opens must never write
            "purpose: Keeps notes for the user.\nrequests: {add: {description: Keep one note.}}\n"
            "views: {notes: {request: add, show: table}}\n",
            "manifest.yaml: view 'notes': 'add' changes data; a view only reads",
        ),
        (
            "purpose: Keeps notes for the user.\n"
            "requests: {last: {description: The last note kept., returns: {note: string}}}\n"
            "views: {last: {request: last, path: text, show: details}}\n",
            "last returns no 'text'; it returns note",
        ),
    ],
)
def test_pin_manifest_problems(tmp_path, text, expect):
    (tmp_path / "manifest.yaml").write_text(text)
    manifest, problems = pin_manifest(tmp_path, "notes", "0.1.0")
    assert manifest is None and any(expect in p for p in problems), problems


def test_relative_names_say_what_to_write():
    assert relative_names({"emits": ["notes.kept", "kept"]}, "notes") == [
        "manifest.yaml: emits has 'notes.kept'; names are relative: write 'kept'"
    ]


# ---- the code -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, banned",
    [
        ("import subprocess\n", "import subprocess"),
        ("import urllib.request\n", "import urllib.request"),
        ("from http.client import HTTPConnection\n", "from http.client"),
        ("import socket as s\n", "import socket"),
        ("import os\nos.system('ls')\n", ".system"),
        ("import asyncio\nasyncio.create_subprocess_exec('ls')\n", ".create_subprocess_exec"),
        ("eval('1')\n", "eval()"),
        ("__import__('os')\n", "__import__()"),
        ("from mycelium_sdk import NatsBus\n", "NatsBus"),
        ("import nats\n", "import nats"),
        ("x = mod.bus\n", ".bus"),
        ("x = getattr(mod, 'bus')\n", "getattr of 'bus'"),
        ("def f(:\n", "syntax error"),
        ("from os import system\nsystem('ls')\n", "import of system"),
        ("from asyncio import create_subprocess_exec\n", "import of create_subprocess_exec"),
        ("import os\nos.posix_spawn('/bin/sh', [], {})\n", ".posix_spawn"),
        ("import os\nos.spawnvp(0, 'sh', [])\n", ".spawnvp"),
        ("import builtins\n", "import builtins"),
        ("x = __builtins__\n", "__builtins__"),
        ("import math\nmath.eval('1')\n", ".eval"),
        ("x = getattr(obj, 'exec')\n", "getattr of 'exec'"),
    ],
)
def test_check_python_bans(code, banned):
    problems = check_python("app/main.py", code, app=True)
    assert any(banned in p for p in problems), problems
    assert problems[0].startswith("app/main.py:")


def test_ordinary_code_passes():
    code = "import re\nimport sqlite3\nfrom datetime import date\nPATTERN = re.compile(r'\\d+')\n"
    assert check_python("app/main.py", code, app=True) == []


def test_tests_may_hold_a_bus_but_not_open_a_socket():
    code = "x = fixture.bus\nreply = bus.request('rpc.mod.notes.last', {})\n"
    assert check_python("tests/test_notes.py", code, app=False) == []
    assert check_python("tests/test_notes.py", "import socket\n", app=False)


def test_the_example_module_passes_the_checks():
    files = {rel: GOOD[rel] for rel in GOOD}
    assert check_files(TEMPLATE, files) == []


def test_check_files_size_and_main(tmp_path):
    problems = check_files(tmp_path, {"app/helper.py": "x = '" + "a" * 50_000 + "'\n"})
    assert any("app/helper.py" in p and "bytes" in p for p in problems)
    assert "app/main.py is missing" in problems


# ---- GROWN_DIR as a repo ------------------------------------------------------------------------------


async def test_repo_commits_a_module_and_tags_it(tmp_path):
    repo = GrownRepo(tmp_path)
    await repo.ensure()
    await repo.ensure()  # twice is fine
    assert (tmp_path / ".git").exists() and ".staging/" in (tmp_path / ".gitignore").read_text()
    (tmp_path / ".staging" / "wip").mkdir(parents=True)
    (tmp_path / ".staging" / "wip" / "x.py").write_text("x")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "manifest.yaml").write_text("name: notes\n")
    sha = await repo.commit("notes", "0.1.0", "notes v0.1.0\n\nbody")
    assert sha == git(tmp_path, "rev-parse", "--short=12", "HEAD").strip()
    assert git(tmp_path, "log", "-1", "--format=%s").strip() == "notes v0.1.0"
    assert git(tmp_path, "tag", "-l").split() == ["notes-v0.1.0"]
    assert ".staging" not in git(tmp_path, "ls-files")
