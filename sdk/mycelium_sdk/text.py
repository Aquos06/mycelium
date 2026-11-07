"""Text made to fit: a line on a card, an excerpt in a prompt.

cut("a long error ...", 160)          -> at most 160 characters, an ellipsis where it was cut
one_line("FAILED x\\n  y", 200)        -> the same, on one line
"""

from __future__ import annotations


def cut(text: str, n: int) -> str:
    """`text` in at most `n` characters: as it is, or cut short with an ellipsis."""
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def one_line(text: str, n: int) -> str:
    """`text` on one line (every run of whitespace one space), in at most `n` characters."""
    return cut(" ".join(text.split()), n)
