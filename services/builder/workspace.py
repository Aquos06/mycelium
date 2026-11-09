"""A build's folder: scaffolded from template/, written by a coder, tidied after every round, promoted when it passes.

    GROWN_DIR/.staging/<name>/            the build in progress (the supervisor verifies it there, never deploys it)
    GROWN_DIR/<name>/                     a module that passed, committed in GROWN_DIR's git repo
    GROWN_DIR/.staging/<name>.previous/   a change build's promote: the version it replaces, until it is committed

A new module starts from template/; a change starts from a copy of the module as it is (start_change).

A coder may write only manifest.yaml, app/<x>.py and tests/test_<x>.py. Everything else is
the builder's: the template's protected files are put back after every round, SPEC.md and the contract test
are rewritten, and anything a coder left outside those paths (a stray file, a symlink, a cache) is removed.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from mycelium_sdk.manifest import NAME_RE

from .contract import CONTRACT_TEST

STAGING = ".staging"
PREVIOUS = ".previous"  # no module name has a dot, so this never names a build
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".txt", ".ini", ""}
PROTECTED = (  # from template/, put back after every round
    "Dockerfile",
    ".dockerignore",
    "requirements.txt",  # standard library only this round; the Dockerfile copies it, so it must be there
    "CONTRACT.md",
    "pytest.ini",
    "app/__init__.py",
    "tests/conftest.py",
)
SPEC = "SPEC.md"
CONTRACT = "tests/test_contract.py"
PY_FILE = re.compile(r"^[a-z_][a-z0-9_]*\.py\Z")
JUNK = ("__pycache__", ".pytest_cache")


def scaffold(name: str, dest_root: Path, template: Path) -> Path:
    """dest_root/<name>/ from the template, with __NAME__ filled in."""
    if not NAME_RE.match(name):
        raise ValueError(f"invalid module name: {name!r} (lowercase slug, 2-31 chars)")
    dest = dest_root / name
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    shutil.copytree(template, dest, ignore=shutil.ignore_patterns(*JUNK))
    for p in dest.rglob("*"):
        if p.is_file() and p.suffix in TEXT_SUFFIXES and p.name != "Dockerfile":
            text = p.read_text()
            if "__NAME__" in text:
                p.write_text(text.replace("__NAME__", name))
    return dest


def coder_may_write(rel: str) -> bool:
    """The paths a coder owns: the manifest, flat app/ modules and tests/test_*.py."""
    if rel == "manifest.yaml":
        return True
    parts = rel.split("/")
    if len(parts) != 2 or not PY_FILE.match(parts[1]):
        return False
    folder, file = parts
    if folder == "app":
        return file != "__init__.py"
    return folder == "tests" and file.startswith("test_") and rel != CONTRACT


def read_files(module_dir: Path, *prefixes: str) -> dict[str, str]:
    """What a coder reads back ({path: text}): its own files and the contract test it has to pass."""
    out: dict[str, str] = {}
    for p in sorted(module_dir.rglob("*")):
        rel = p.relative_to(module_dir).as_posix()
        if p.is_file() and not p.is_symlink() and (coder_may_write(rel) or rel == CONTRACT):
            if not prefixes or rel.startswith(prefixes):
                out[rel] = p.read_text(errors="replace")
    return out


def write_file(module_dir: Path, rel: str, content: str) -> None:
    """A coder's file, or a ValueError naming the paths it may write."""
    if not coder_may_write(rel):
        raise ValueError(f"{rel!r} is not yours to write: manifest.yaml, app/<x>.py, tests/test_<x>.py")
    p = module_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.is_symlink():
        p.unlink()
    p.write_text(content)


class Workspace:
    def __init__(self, grown: Path, template: Path) -> None:
        self.grown = grown
        self.template = template

    def staging(self, name: str) -> Path:
        return self.grown / STAGING / name

    def module(self, name: str) -> Path:
        return self.grown / name

    def previous(self, name: str) -> Path:
        return self.grown / STAGING / f"{name}{PREVIOUS}"

    def exists(self, name: str) -> bool:
        return self.module(name).is_dir()

    def spec(self, name: str) -> str:
        """The module's SPEC.md as it was last built: what Hansen approved, and every change since."""
        p = self.module(name) / SPEC
        return p.read_text() if p.is_file() else ""

    def start(self, name: str, spec: str) -> Path:
        """A fresh staging folder: whatever an earlier build of this name left there goes."""
        d = self._clear(name)
        scaffold(name, d.parent, self.template)
        (d / SPEC).write_text(spec)
        (d / CONTRACT).write_text(CONTRACT_TEST)  # a coding agent runs it from the first round
        return d

    def start_change(self, name: str, spec: str) -> Path:
        """A change build's staging folder: a copy of the module as it is, with the new SPEC.md. The module keeps
        running from its own folder until the change is verified, committed and deployed."""
        d = self._clear(name)
        shutil.copytree(self.module(name), d, symlinks=True, ignore=shutil.ignore_patterns(*JUNK))
        (d / SPEC).write_text(spec)
        (d / CONTRACT).write_text(CONTRACT_TEST)
        return d

    def _clear(self, name: str) -> Path:
        if not NAME_RE.match(name):
            raise ValueError(f"invalid module name: {name!r} (lowercase slug, 2-31 chars)")
        d = self.staging(name)
        if d.exists():
            shutil.rmtree(d)
        d.parent.mkdir(parents=True, exist_ok=True)
        return d

    def tidy(self, name: str, spec: str) -> list[str]:
        """After a coder: the builder's files back as they were, everything the coder may not write removed.
        Returns what was removed, so the round can say so."""
        d = self.staging(name)
        _drop_junk(d)
        removed: list[str] = []
        for p in sorted(d.rglob("*"), key=lambda p: len(p.parts)):  # shallowest first: a folder takes its files
            if not p.is_symlink() and not p.exists():
                continue  # inside a folder removed already
            rel = p.relative_to(d).as_posix()
            if p.is_symlink():
                p.unlink()
                removed.append(rel)
            elif p.is_dir():
                if rel not in ("app", "tests"):
                    shutil.rmtree(p)
                    removed.append(rel + "/")
            elif not (coder_may_write(rel) or rel in PROTECTED or rel in (SPEC, CONTRACT)):
                p.unlink()
                removed.append(rel)
        for rel in PROTECTED:
            src = self.template / rel
            text = src.read_text()
            if src.name != "Dockerfile":
                text = text.replace("__NAME__", name)
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text)
        (d / SPEC).write_text(spec)
        (d / CONTRACT).write_text(CONTRACT_TEST)
        return removed

    def files(self, name: str) -> dict[str, str]:
        return read_files(self.staging(name))

    def promote(self, name: str, replace: bool = False) -> Path:
        """Staging becomes the module. With `replace` (a change) the version there moves aside until `settle`."""
        src, dest = self.staging(name), self.module(name)
        if dest.exists():
            if not replace:
                raise FileExistsError(f"{dest} already exists")
            old = self.previous(name)
            if old.exists():
                shutil.rmtree(old)
            dest.rename(old)
        _drop_junk(src)
        src.rename(dest)
        return dest

    def demote(self, name: str) -> None:
        """Undo promote (a commit that failed): the module goes back to staging, out of GROWN_DIR, and the version
        a change replaced comes back."""
        src, dest, old = self.module(name), self.staging(name), self.previous(name)
        if src.exists() and not dest.exists():
            src.rename(dest)
        if old.exists() and not src.exists():
            old.rename(src)

    def settle(self, name: str) -> None:
        """The change is committed: the version it replaced lives in git (its tag), not on disk."""
        shutil.rmtree(self.previous(name), ignore_errors=True)

    def discard(self, name: str) -> None:
        """The module is deleted: what a build of it left in staging goes too, so nothing of it is on disk."""
        if not NAME_RE.match(name):
            raise ValueError(f"invalid module name: {name!r} (lowercase slug, 2-31 chars)")
        for d in (self.staging(name), self.previous(name)):
            shutil.rmtree(d, ignore_errors=True)


def _drop_junk(d: Path) -> None:
    """Caches a test run leaves behind; never part of a module."""
    for p in [p for p in d.rglob("*") if p.is_dir() and not p.is_symlink() and p.name in JUNK]:
        shutil.rmtree(p, ignore_errors=True)
