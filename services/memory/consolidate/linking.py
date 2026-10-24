"""Ordinary code around the model's text: link what it left bare, compare lines without their links."""

from __future__ import annotations

import re
from datetime import date

from ..schemas import Note
from ..vault import LINK_RE

CJK_RE = re.compile(r"[぀-ヿ一-鿿]")


def autolink(text: str, vocabulary: list[tuple[str, str]]) -> str:
    """Wrap known names and aliases the model left bare in [[slug|term]], once per note, outside existing links.

    Ordinary code, not model compliance: the summary links like the rest of the vault, so recall can hop.
    """
    spans = [m.span() for m in LINK_RE.finditer(text)]
    linked = {m.group(1).strip().lower() for m in LINK_RE.finditer(text)}
    for term, name in sorted(vocabulary, key=lambda t: -len(t[0])):
        if name in linked or len(term) < 2:
            continue
        pattern = re.escape(term) if CJK_RE.search(term) else r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        for m in re.finditer(pattern, text, re.IGNORECASE):
            if any(s <= m.start() < e for s, e in spans):
                continue
            shown = m.group(0)
            link = f"[[{name}]]" if shown.lower() == name else f"[[{name}|{shown}]]"
            text = text[: m.start()] + link + text[m.end() :]
            spans = [m2.span() for m2 in LINK_RE.finditer(text)]
            linked.add(name)
            break
    return text


def plain(text: str) -> str:
    """The line without link syntax ([[slug|label]] -> label, [[slug]] -> slug), collapsed, lowercased."""

    def unlink(m: re.Match[str]) -> str:
        inner = m.group(0)[2:-2]
        return inner.split("|", 1)[1] if "|" in inner else inner.split("#", 1)[0]

    return " ".join(LINK_RE.sub(unlink, text).split()).lower()


def has_fact(note: Note, day: date, text: str) -> bool:
    """Idempotency: the same line is already on the note for that day, links or no links."""
    wanted = plain(text)
    return any(f.day == day and plain(f.text) == wanted for f in note.facts)
