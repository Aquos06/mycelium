"""The memory service on the bus.

    rpc.memory.remember   {note, type?, aliases?, summary?, fact?: {day?, text}, source?}
    rpc.memory.lookup     {name}
    rpc.memory.recall     {query, budget?, today?}
    rpc.memory.reindex    {}
    sys.module.deployed   -> writes modules/<name>.md from the manifest

Replies are {"ok": true, ...} or {"ok": false, "error": ...}, like the supervisor's.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from mycelium_sdk.bus import Bus, Message

from .events import EventSource
from .index import Index
from .indexer import index_file, reindex
from .recall import lookup, recall
from .vault import NAME_RE, TYPES, Fact, Note, Vault

log = logging.getLogger("mycelium.memory")

DEFAULT_BUDGET = 8


class MemoryService:
    def __init__(
        self,
        bus: Bus,
        vault: Vault,
        index: Index,
        events: EventSource | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.bus = bus
        self.vault = vault
        self.index = index
        self.events = events
        self.today = today

    async def start(self) -> None:
        await self.bus.connect()
        stats = await reindex(self.vault, self.index)
        log.info("indexed vault: %s", stats)
        await self.bus.subscribe("rpc.memory.remember", self._wrap(self.remember), queue="memory")
        await self.bus.subscribe("rpc.memory.lookup", self._wrap(self.lookup), queue="memory")
        await self.bus.subscribe("rpc.memory.recall", self._wrap(self.recall), queue="memory")
        await self.bus.subscribe("rpc.memory.reindex", self._wrap(self.reindex), queue="memory")
        await self.bus.subscribe("sys.module.deployed", self.on_module_deployed, queue="memory")

    def _wrap(self, fn):
        async def handler(msg: Message) -> None:
            try:
                payload = {"ok": True, **await fn(msg.data)}
            except (ValueError, KeyError, TypeError) as e:
                payload = {"ok": False, "error": str(e)}
            except Exception as e:  # never let a handler take the service down
                log.exception("memory handler failed on %s", msg.subject)
                payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if msg.reply:
                await msg.respond(payload)

        return handler

    # ---- handlers ------------------------------------------------------------------------

    async def remember(self, data: dict[str, Any]) -> dict[str, Any]:
        name = str(data.get("note", "")).strip().lower()
        if not NAME_RE.match(name):
            raise ValueError(f"bad note name: {name!r}")
        fact = data.get("fact")
        summary = data.get("summary")
        if not fact and not summary:
            raise ValueError("a fact or a summary is required")

        existing = await self.index.get(name)
        if existing:
            note = self.vault.read(existing.path)
            created = False
        else:
            note_type = str(data.get("type") or "thing")
            if note_type not in TYPES:
                raise ValueError(f"unknown note type: {note_type!r}")
            note = Note(name=name, path=self.vault.path_for(name, note_type), type=note_type)
            created = True

        for alias in data.get("aliases") or []:
            a = str(alias).strip().lower()
            if a and a not in note.aliases:
                note.aliases.append(a)
        if summary:
            note.summary = " ".join(str(summary).split())
        if fact:
            text = " ".join(str(fact.get("text", "")).split())
            if not text:
                raise ValueError("fact.text is required")
            day = date.fromisoformat(fact["day"]) if fact.get("day") else self.today()
            note.facts.insert(0, Fact(day, text, data.get("source")))

        self.vault.write(note)
        await index_file(self.vault, self.index, note.path)
        return {"path": note.path, "created": created}

    async def lookup(self, data: dict[str, Any]) -> dict[str, Any]:
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("name is required")
        matches = await lookup(self.index, name)
        return {
            "matches": [
                {"name": m.record.name, "path": m.record.path, "type": m.record.type, "via": m.via, "score": m.score}
                for m in matches
            ]
        }

    async def recall(self, data: dict[str, Any]) -> dict[str, Any]:
        query = str(data.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        budget = int(data.get("budget") or DEFAULT_BUDGET)
        today = date.fromisoformat(data["today"]) if data.get("today") else self.today()
        return await recall(self.vault, self.index, query, today=today, budget=budget)

    async def reindex(self, _data: dict[str, Any]) -> dict[str, Any]:
        stats = await reindex(self.vault, self.index)
        return {"notes": stats.notes, "summaries": stats.summaries, "skipped": stats.skipped}

    async def on_module_deployed(self, msg: Message) -> None:
        name = str(msg.data.get("name", "")).strip().lower()
        version = str(msg.data.get("version", "")).strip()
        if not NAME_RE.match(name):
            return
        try:
            manifest = await self._manifest_for(name)
            existing = await self.index.get(name)
            note = (
                self.vault.read(existing.path)
                if existing
                else Note(name=name, path=self.vault.path_for(name, "module"), type="module")
            )
            purpose = str(manifest.get("purpose") or f"Module {name}.").strip()
            requests = [f"`rpc.mod.{name}.{a}`" for a in manifest.get("requests") or []]
            asks = f" Exact data lives in the module: ask {', '.join(requests)}." if requests else ""
            note.summary = f"{purpose}{asks}"
            note.facts.insert(0, Fact(self.today(), f"deployed v{version}" if version else "deployed", "sys"))
            self.vault.write(note)
            await index_file(self.vault, self.index, note.path)
        except Exception:
            log.exception("could not write module note for %s", name)

    async def _manifest_for(self, name: str) -> dict[str, Any]:
        try:
            reply = await self.bus.request("rpc.sys.list", {}, timeout=5.0)
        except Exception as e:
            log.warning("rpc.sys.list unavailable (%s); writing a minimal module note", e)
            return {}
        for row in reply.get("modules") or []:
            if row.get("name") == name:
                return row.get("manifest") or {}
        return {}
