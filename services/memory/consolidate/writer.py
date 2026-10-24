"""A DayDigest into the vault: facts onto the notes they belong to, new notes, rewritten states, the day
summary. Writes only what changed, so a hand-edited note with nothing new is left alone."""

from __future__ import annotations

import logging
from datetime import date

from ..index import Index
from ..indexer import index_file
from ..schemas import ConsolidationReport, DayDigest, Event, Fact, Note, NoteType
from ..vault import Vault, summary_path
from .linking import autolink, has_fact, plain

log = logging.getLogger("mycelium.memory.consolidate")


class DigestWriter:
    def __init__(self, vault: Vault, index: Index) -> None:
        self.vault = vault
        self.index = index

    async def apply(self, day: date, digest: DayDigest, events: list[Event], report: ConsolidationReport) -> None:
        known_ids = {e.id for e in events}
        touched: dict[str, Note] = {}
        changed: set[str] = set()
        created: set[str] = set()
        pending: list[tuple[Note, str, str]] = []  # note, the fact as written, provenance

        async def note_for(slug: str, type: NoteType | None, aliases: list[str]) -> Note:
            if slug in touched:
                note = touched[slug]
            elif record := await self.index.get(slug):
                note = self.vault.read(record.path)
            else:
                note_type = type or "thing"
                note = Note(name=slug, path=self.vault.path_for(slug, note_type), type=note_type)
                created.add(slug)
                changed.add(slug)
            for alias in aliases:
                if alias not in note.aliases and alias != note.name:
                    note.aliases.append(alias)
                    changed.add(slug)
            touched[slug] = note
            return note

        for f in digest.facts:
            note = await note_for(f.note, f.type, f.aliases)
            ids = [i for i in f.events if i in known_ids]  # the model may misremember an id
            source = f"ev:{ids[0]}" if ids else "consolidation"
            if has_fact(note, day, f.text) or any(n is note and plain(t) == plain(f.text) for n, t, _ in pending):
                report.facts_skipped += 1
                continue
            pending.append((note, f.text, source))

        for u in digest.updates:
            if u.note not in touched and await self.index.get(u.note) is None:
                log.info("update for unknown note %r ignored", u.note)
                continue
            note = await note_for(u.note, None, [])
            if note.summary != u.summary:
                note.summary = u.summary
                changed.add(u.note)

        # link with what the vault knows now: this run's new notes and aliases included
        vocabulary = await self.index.vocabulary()
        for note in touched.values():
            vocabulary.append((note.name, note.name))
            vocabulary.extend((a, note.name) for a in note.aliases if a != note.name)
        for note, text, source in pending:
            note.facts.insert(0, Fact(day=day, text=autolink(text, vocabulary), source=source))
            changed.add(note.name)
            report.facts_added += 1

        for slug in sorted(changed):
            self.vault.write(touched[slug])
            await index_file(self.vault, self.index, touched[slug].path)
        report.notes_created = sorted(created)
        report.notes_updated = sorted(changed - created)

        path = summary_path(day)
        self.vault.write_text(path, autolink(digest.summary, vocabulary))
        await index_file(self.vault, self.index, path)
        report.summary_path = path
