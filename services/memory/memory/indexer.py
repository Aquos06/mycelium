"""Vault -> index. The only thing that writes the index. Incremental by content hash."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from .index import Index, NoteRecord, SummaryRecord
from .vault import Vault, parse_note, parse_summary


@dataclass
class IndexStats:
    notes: int = 0
    summaries: int = 0
    skipped: int = 0


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def index_file(vault: Vault, index: Index, path: str) -> bool:
    """Index one file. Returns False when its content hash is unchanged."""
    text = vault.raw(path)
    h = content_hash(text)
    if await index.body_hash(path) == h:
        return False
    if path.startswith("summaries/"):
        s = parse_summary(path, text)
        await index.upsert_summary(SummaryRecord(s.period, s.key, s.path, s.text, s.links, body_hash=h))
    else:
        n = parse_note(path, text)
        record = NoteRecord(
            name=n.name,
            path=n.path,
            type=n.type,
            aliases=n.aliases,
            summary=n.summary,
            links=n.links,
            body_hash=h,
            updated_at=datetime.now(UTC),
        )
        await index.upsert_note(record, n.facts)
    return True


async def reindex(vault: Vault, index: Index) -> IndexStats:
    stats = IndexStats()
    for path in vault.paths():
        try:
            changed = await index_file(vault, index, path)
        except ValueError:
            continue  # a file under summaries/ that is not a summary
        if not changed:
            stats.skipped += 1
        elif path.startswith("summaries/"):
            stats.summaries += 1
        else:
            stats.notes += 1
    return stats
