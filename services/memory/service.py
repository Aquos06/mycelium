"""The memory service on the bus.

    rpc.memory.remember     RememberRequest    -> RememberReply
    rpc.memory.lookup       LookupRequest      -> LookupReply
    rpc.memory.recall       RecallRequest      -> RecallPack
    rpc.memory.reindex      {}                 -> IndexStats
    rpc.memory.consolidate  ConsolidateRequest -> ConsolidationReport   (default: yesterday)
    rpc.memory.rollup       RollupRequest      -> RollupReport           (a week or month from its days)
    sys.module.deployed     -> writes modules/<name>.md from the manifest

Payloads are validated with the models in schemas/rpc.py (the contract Main codes against).
Replies are {"ok": true, ...} or {"ok": false, "error": ...}, like the supervisor's.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError

from mycelium_sdk import Bus, Message, validation_message

from .consolidate import Consolidator
from .index import Index
from .indexer import index_file, reindex
from .recall import lookup, recall
from .schemas import (
    NAME_RE,
    ConsolidateRequest,
    Fact,
    LookupMatch,
    LookupReply,
    LookupRequest,
    Note,
    RecallRequest,
    RememberReply,
    RememberRequest,
    RollupRequest,
)
from .vault import Vault

log = logging.getLogger("mycelium.memory")


class MemoryService:
    def __init__(
        self,
        bus: Bus,
        vault: Vault,
        index: Index,
        consolidator: Consolidator | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.bus = bus
        self.vault = vault
        self.index = index
        self.consolidator = consolidator
        self.today = today

    async def start(self) -> None:
        await self.bus.connect()
        stats = await reindex(self.vault, self.index)
        log.info("indexed vault: %s", stats)
        await self.bus.subscribe("rpc.memory.remember", self._wrap(self.remember), queue="memory")
        await self.bus.subscribe("rpc.memory.lookup", self._wrap(self.lookup), queue="memory")
        await self.bus.subscribe("rpc.memory.recall", self._wrap(self.recall), queue="memory")
        await self.bus.subscribe("rpc.memory.reindex", self._wrap(self.reindex), queue="memory")
        await self.bus.subscribe("rpc.memory.consolidate", self._wrap(self.consolidate), queue="memory")
        await self.bus.subscribe("rpc.memory.rollup", self._wrap(self.rollup), queue="memory")
        await self.bus.subscribe("sys.module.deployed", self.on_module_deployed, queue="memory")

    def _wrap(self, fn):
        async def handler(msg: Message) -> None:
            try:
                reply: BaseModel = await fn(msg.data)
                payload = {"ok": True, **reply.model_dump(mode="json")}
            except ValidationError as e:
                payload = {"ok": False, "error": validation_message(e)}
            except (ValueError, KeyError, TypeError) as e:
                payload = {"ok": False, "error": str(e)}
            except Exception as e:  # never let a handler take the service down
                log.exception("memory handler failed on %s", msg.subject)
                payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if msg.reply:
                await msg.respond(payload)

        return handler

    # ---- handlers ------------------------------------------------------------------------

    async def remember(self, data: dict[str, Any]) -> RememberReply:
        req = RememberRequest.model_validate(data)

        existing = await self.index.get(req.note)
        if existing:
            note = self.vault.read(existing.path)
            created = False
        else:
            note_type = req.type or "thing"
            note = Note(name=req.note, path=self.vault.path_for(req.note, note_type), type=note_type)
            created = True

        for alias in req.aliases:
            if alias not in note.aliases:
                note.aliases.append(alias)
        if req.summary:
            note.summary = req.summary
        if req.fact:
            note.facts.insert(0, Fact(day=req.fact.day or self.today(), text=req.fact.text, source=req.source))

        self.vault.write(note)
        await index_file(self.vault, self.index, note.path)
        return RememberReply(path=note.path, created=created)

    async def lookup(self, data: dict[str, Any]) -> LookupReply:
        req = LookupRequest.model_validate(data)
        matches = await lookup(self.index, req.name)
        return LookupReply(
            matches=[
                LookupMatch(name=m.record.name, path=m.record.path, type=m.record.type, via=m.via, score=m.score)
                for m in matches
            ]
        )

    async def recall(self, data: dict[str, Any]):
        req = RecallRequest.model_validate(data)
        return await recall(self.vault, self.index, req.query, today=req.today or self.today(), budget=req.budget)

    async def reindex(self, _data: dict[str, Any]):
        return await reindex(self.vault, self.index)

    async def consolidate(self, data: dict[str, Any]):
        req = ConsolidateRequest.model_validate(data)
        if self.consolidator is None:
            raise ValueError("consolidation is not configured (no event source)")
        day = req.day or self.today() - timedelta(days=1)
        return await self.consolidator.run(day, cause=str(data.get("id")) if data.get("id") else None)

    async def rollup(self, data: dict[str, Any]):
        req = RollupRequest.model_validate(data)
        if self.consolidator is None:
            raise ValueError("consolidation is not configured (no event source)")
        return await self.consolidator.rollup(
            req.period, req.key, cause=str(data.get("id")) if data.get("id") else None
        )

    async def on_module_deployed(self, msg: Message) -> None:
        name = str(msg.data.get("name", "")).strip().lower()
        version = str(msg.data.get("version", "")).strip()
        if not NAME_RE.match(name):
            return
        try:
            manifest = await self._manifest_for(name)
            existing = await self.index.get(name)
            if existing:
                note = self.vault.read(existing.path)
            else:
                note = Note(name=name, path=self.vault.path_for(name, "module"), type="module")
            purpose = str(manifest.get("purpose") or f"Module {name}.").strip()
            requests = [f"`rpc.mod.{name}.{a}`" for a in manifest.get("requests") or []]
            asks = f" Exact data lives in the module: ask {', '.join(requests)}." if requests else ""
            note.summary = f"{purpose}{asks}"
            note.facts.insert(
                0, Fact(day=self.today(), text=f"deployed v{version}" if version else "deployed", source="sys")
            )
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
