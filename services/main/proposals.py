"""Proposals: a module Main drafted, kept in Main's KV until it is built or turned down.

A proposal is stored before its card goes out, under the card's own id (the `ref` a tap carries back), so a
tap on Build it starts the build in code, never through the model: the approval is enforced here, not in the
prompt. A second tap, or a tap on an old card, finds the proposal already decided.

    proposed -> building -> done | failed
             -> declined
    proposed stays proposed when the builder would not start (down, busy, name taken): nothing was built,
    and Main sends a fresh card for it, since the apps take the buttons off a card once it is answered.

Keys in Main's bucket:
    proposal/<id>              the proposal; <id> is its first card's id
    proposal-card/<card id>    a later card for the same proposal -> its id
    proposal-build/<build id>  -> the proposal that started that build (build.done / build.failed)
    proposal-name/<name>       -> the latest proposal of that name (a build whose start timed out)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from mycelium_sdk import KV, kv_key, now_iso

PREFIX = "proposal"
BY_CARD = "proposal-card"
BY_BUILD = "proposal-build"
BY_NAME = "proposal-name"
NOTE_SHOWN = 300  # characters of a note told in the chat


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    DECLINED = "declined"
    BUILDING = "building"
    DONE = "done"
    FAILED = "failed"


class Proposal(BaseModel):
    id: str  # its first card's id (out.ask)
    name: str
    purpose: str
    spec: str  # SPEC.md, as Hansen approves it
    channel: str
    thread: str
    cause: str | None = None  # the message Main was answering when it proposed
    status: ProposalStatus = ProposalStatus.PROPOSED
    created: str = Field(default_factory=now_iso)
    decided: str | None = None
    build_id: str | None = None
    note: str | None = None  # the last thing that went wrong: why the builder would not start, where it failed

    def short_note(self) -> str:
        note = self.note or "no reason given"
        return note if len(note) <= NOTE_SHOWN else note[:NOTE_SHOWN] + "…"


class Link(BaseModel):
    proposal: str


class ProposalStore:
    def __init__(self, kv: KV) -> None:
        self.kv = kv

    async def get(self, proposal_id: str) -> Proposal | None:
        raw = await self.kv.get(kv_key(PREFIX, proposal_id))
        return Proposal.model_validate(raw) if raw is not None else None

    async def save(self, proposal: Proposal) -> None:
        await self.kv.put(kv_key(PREFIX, proposal.id), proposal.model_dump(mode="json"))
        if proposal.build_id:
            await self._link(BY_BUILD, proposal.build_id, proposal.id)

    async def create(self, proposal: Proposal) -> None:
        """A new proposal: also the latest one of its name."""
        await self.save(proposal)
        await self._link(BY_NAME, proposal.name, proposal.id)

    async def add_card(self, card_id: str, proposal: Proposal) -> None:
        await self._link(BY_CARD, card_id, proposal.id)

    async def by_card(self, card_id: str) -> Proposal | None:
        """The proposal a tap is about: its first card, or a later one."""
        return await self.get(card_id) or await self._follow(BY_CARD, card_id)

    async def by_build(self, build_id: str) -> Proposal | None:
        return await self._follow(BY_BUILD, build_id)

    async def by_name(self, name: str) -> Proposal | None:
        return await self._follow(BY_NAME, name)

    async def building(self) -> list[Proposal]:
        """Every proposal whose build has not been reported yet (Main's catch-up on start). Proposals are a few
        a week, so reading them all is cheaper than keeping an index in step."""
        return [p for p in await self._all() if p.status == ProposalStatus.BUILDING]

    async def offered(self, limit: int = 8) -> list[Proposal]:
        """The latest proposals that are not running modules yet (waiting, declined, building, failed): what the
        planner reads so it does not offer the same module twice."""
        open_ = [p for p in await self._all() if p.status != ProposalStatus.DONE]
        return sorted(open_, key=lambda p: p.created, reverse=True)[:limit]

    async def _all(self) -> list[Proposal]:
        out = []
        for key in await self.kv.keys(f"{PREFIX}/"):
            raw = await self.kv.get(key)
            if raw is not None:
                out.append(Proposal.model_validate(raw))
        return out

    async def _link(self, kind: str, key: str, proposal_id: str) -> None:
        await self.kv.put(kv_key(kind, key), Link(proposal=proposal_id).model_dump())

    async def _follow(self, kind: str, key: str) -> Proposal | None:
        raw = await self.kv.get(kv_key(kind, key))
        return await self.get(Link.model_validate(raw).proposal) if raw is not None else None
