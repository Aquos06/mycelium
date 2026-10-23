"""The memory service on the bus.

    rpc.memory.remember   RememberRequest
    rpc.memory.lookup     LookupRequest
    rpc.memory.recall     RecallRequest
    rpc.memory.reindex    {}
    sys.module.deployed   -> writes modules/<name>.md from the manifest

Request payloads are validated with the pydantic models below (the contract Main codes against).
Replies are {"ok": true, ...} or {"ok": false, "error": ...}, like the supervisor's.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from mycelium_sdk import Bus, Message, validation_message

from .events import EventSource
from .index import Index
from .indexer import index_file, reindex
from .recall import lookup, recall
from .vault import NAME_RE, Fact, Note, Vault

log = logging.getLogger("mycelium.memory")

DEFAULT_BUDGET = 8

NoteType = Literal["self", "person", "place", "project", "thing", "routine", "module"]


def _collapse(text: str) -> str:
    return " ".join(text.split())


class FactIn(BaseModel):
    text: str = Field(min_length=1)
    day: date | None = None  # default: today

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        v = _collapse(v)
        if not v:
            raise ValueError("fact.text is required")
        return v


class RememberRequest(BaseModel):
    note: str
    type: NoteType | None = None  # used only when the note does not exist yet
    aliases: list[str] = Field(default_factory=list)
    summary: str | None = None  # replaces the note's first paragraph
    fact: FactIn | None = None
    source: str | None = None  # ev:<id> | hansen | consolidation | sys

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        v = v.strip().lower()
        if not NAME_RE.match(v):
            raise ValueError(f"bad note name: {v!r}")
        return v

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for a in v:
            a = a.strip().lower()
            if a and a not in out:
                out.append(a)
        return out

    @field_validator("summary")
    @classmethod
    def _summary(cls, v: str | None) -> str | None:
        return _collapse(v) if v is not None else None

    @model_validator(mode="after")
    def _something_to_remember(self) -> RememberRequest:
        if self.fact is None and not self.summary:
            raise ValueError("a fact or a summary is required")
        return self


class LookupRequest(BaseModel):
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        return v


class RecallRequest(BaseModel):
    query: str = Field(min_length=1)
    budget: int = Field(default=DEFAULT_BUDGET, ge=1, le=50)
    today: date | None = None  # for replays and tests; default: the service's clock

    @field_validator("query")
    @classmethod
    def _query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query is required")
        return v


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

    async def remember(self, data: dict[str, Any]) -> dict[str, Any]:
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
        return {"path": note.path, "created": created}

    async def lookup(self, data: dict[str, Any]) -> dict[str, Any]:
        req = LookupRequest.model_validate(data)
        matches = await lookup(self.index, req.name)
        return {
            "matches": [
                {"name": m.record.name, "path": m.record.path, "type": m.record.type, "via": m.via, "score": m.score}
                for m in matches
            ]
        }

    async def recall(self, data: dict[str, Any]) -> dict[str, Any]:
        req = RecallRequest.model_validate(data)
        return await recall(self.vault, self.index, req.query, today=req.today or self.today(), budget=req.budget)

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
