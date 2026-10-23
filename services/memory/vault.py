"""The vault: a folder of markdown notes, one per entity, plus day/week/month summaries.

Files are the truth. Everything in the index is derived from what this module parses. The shapes
(Note, Fact, Summary) live in schemas/vault.py; this module reads and writes them.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import yaml

from .schemas import NAME_RE, Fact, Note, NoteType, Summary

__all__ = ["NAME_RE", "Fact", "Note", "NoteType", "Summary", "Vault"]

TYPES = ("self", "person", "place", "project", "thing", "routine", "module")
FOLDER_TYPES = {
    "people": "person",
    "places": "place",
    "projects": "project",
    "modules": "module",
    "things": "thing",
    "routines": "routine",
}
TYPE_FOLDERS = {v: k for k, v in FOLDER_TYPES.items()}
SOURCES = ("hansen", "consolidation", "sys")

LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
FACT_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) (.*?)(?:\s+\((ev:\d+|hansen|consolidation|sys)\))?\s*$")
DAY_RE = re.compile(r"^summaries/(\d{4})/(\d{2})/(\d{2})\.md$")
WEEK_RE = re.compile(r"^summaries/(\d{4})/W(\d{2})\.md$")
MONTH_RE = re.compile(r"^summaries/(\d{4})/(\d{2})\.md$")


def summary_path(day: date) -> str:
    return f"summaries/{day:%Y/%m/%d}.md"


def type_for_path(path: str) -> str:
    parts = Path(path).parts
    if len(parts) == 1:
        return "self" if parts[0] == "hansen.md" else "thing"
    return FOLDER_TYPES.get(parts[0], "thing")


def extract_links(text: str) -> list[str]:
    seen: list[str] = []
    for m in LINK_RE.finditer(text):
        target = m.group(1).strip().lower()
        if target and target not in seen:
            seen.append(target)
    return seen


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    try:
        fm = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), body


def parse_note(path: str, text: str) -> Note:
    fm, body = _split_frontmatter(text)
    note_type = str(fm.get("type") or type_for_path(path))
    aliases = [str(a).strip().lower() for a in (fm.get("aliases") or []) if str(a).strip()]

    facts: list[Fact] = []
    summary_lines: list[str] = []
    in_summary = False
    summary_done = False
    for line in body.splitlines():
        m = FACT_RE.match(line)
        if m:
            summary_done = True
            facts.append(Fact(day=date.fromisoformat(m.group(1)), text=m.group(2).strip(), source=m.group(3)))
            continue
        if not line.strip():
            if in_summary:
                summary_done = True
            continue
        if not summary_done:
            in_summary = True
            summary_lines.append(line.strip())

    summary = " ".join(summary_lines)
    links = extract_links(summary + "\n" + "\n".join(f.text for f in facts))
    return Note(
        name=Path(path).stem, path=path, type=note_type, aliases=aliases, summary=summary, links=links, facts=facts
    )


def _yaml_scalar(value: str) -> str:
    if re.search(r"[:#,\[\]{}\"'\n]", value) or value != value.strip():
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def render_note(note: Note) -> str:
    aliases = ", ".join(_yaml_scalar(a) for a in note.aliases)
    out = ["---", f"type: {note.type}", f"aliases: [{aliases}]", "---"]
    if note.summary:
        out.append(note.summary)
    if note.facts:
        out.append("")
        for f in sorted(note.facts, key=lambda f: f.day, reverse=True):
            line = f"- {f.day.isoformat()} {f.text}"
            if f.source:
                line += f"  ({f.source})"
            out.append(line)
    return "\n".join(out) + "\n"


def parse_summary(path: str, text: str) -> Summary:
    if m := DAY_RE.match(path):
        period, key = "day", f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    elif m := WEEK_RE.match(path):
        period, key = "week", f"{m.group(1)}-W{m.group(2)}"
    elif m := MONTH_RE.match(path):
        period, key = "month", f"{m.group(1)}-{m.group(2)}"
    else:
        raise ValueError(f"not a summary path: {path}")
    body = _split_frontmatter(text)[1].strip()
    return Summary(period=period, key=key, path=path, text=body, links=extract_links(body))


class Vault:
    """Reads and writes notes under one root. Never lets a path escape it."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        p = (self.root / path).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"path escapes the vault: {path}")
        return p

    def path_for(self, name: str, type: str) -> str:
        if not NAME_RE.match(name):
            raise ValueError(f"bad note name: {name!r}")
        if type == "self":
            return f"{name}.md"
        if type not in TYPE_FOLDERS:
            raise ValueError(f"unknown note type: {type!r}")
        return f"{TYPE_FOLDERS[type]}/{name}.md"

    def exists(self, path: str) -> bool:
        return self._resolve(path).is_file()

    def raw(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def read(self, path: str) -> Note:
        return parse_note(path, self.raw(path))

    def write(self, note: Note) -> None:
        p = self._resolve(note.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_note(note), encoding="utf-8")

    def write_text(self, path: str, text: str) -> None:
        """A summary file (notes go through write(), which renders them)."""
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")

    def paths(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*.md")
            if p.is_file() and not any(part.startswith(".") for part in p.relative_to(self.root).parts)
        )

    def notes(self) -> Iterator[Note]:
        for path in self.paths():
            if not path.startswith("summaries/"):
                yield self.read(path)

    def summaries(self) -> Iterator[Summary]:
        for path in self.paths():
            if path.startswith("summaries/"):
                try:
                    yield parse_summary(path, self.raw(path))
                except ValueError:
                    continue
