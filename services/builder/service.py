"""The builder on the bus.

    rpc.build.start   BuildRequest       -> StartReply
    rpc.build.get     BuildRef           -> BuildRecord
    rpc.build.list    BuildListRequest   -> BuildList (newest first)
    rpc.build.coders  {}                 -> CoderList
The handler adds ok=true; errors are {"ok": false, "error"}.
Events:
    build.started / build.progress (one per round) / build.done / build.failed

A build starts by request, not by event: an event would vanish while the builder is down (core NATS has no
durable consumers here), a request gets an answer or an error. A name that exists, a full queue, a coder that
cannot work or a supervisor that does not answer is refused at once, with the reason. One build runs at a
time; the rest wait in line. Records live in the `builder` KV bucket. A restart fails the build that was
running (its folder is half written) and puts the waiting ones back in line.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from mycelium_sdk import KV, Bus, Message, NoAnswer, Refused, ask, kv_key, now_iso, validation_message

from .coders import Coder, CoderUnavailable
from .pipeline import Pipeline, PipelineError
from .schemas import (
    BuildDone,
    BuildFailed,
    BuildList,
    BuildListRequest,
    BuildProgress,
    BuildRecord,
    BuildRef,
    BuildRequest,
    BuildStarted,
    BuildStatus,
    BuildSummary,
    CoderInfo,
    CoderList,
    ModulesReply,
    Round,
    Stage,
    StartReply,
)
from .workspace import Workspace

log = logging.getLogger("mycelium.builder")

PREFIX = "builds"
KEEP = 200  # records kept in KV; older finished ones go on start


class BuilderService:
    def __init__(
        self,
        bus: Bus,
        kv: KV,
        pipeline: Pipeline,
        workspace: Workspace,
        coders: dict[str, Coder],
        default_coder: str,
        max_queue: int = 5,
        build_timeout: float = 3600.0,
    ) -> None:
        if default_coder not in coders:
            raise ValueError(f"BUILDER_CODER={default_coder!r}: one of {', '.join(coders)}")
        self.bus = bus
        self.kv = kv
        self.pipeline = pipeline
        self.workspace = workspace
        self.coders = coders
        self.default_coder = default_coder
        self.max_queue = max_queue
        self.build_timeout = build_timeout
        self._waiting: list[BuildRecord] = []
        self._current: BuildRecord | None = None
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None

    async def start(self) -> None:
        await self.recover()  # before the first request: a build started now must not be recovered twice
        handlers = {"start": self.start_build, "get": self.get, "list": self.list, "coders": self.list_coders}
        for action, fn in handlers.items():
            await self.bus.subscribe(f"rpc.build.{action}", self._wrap(fn), queue="builder")
        self._worker = asyncio.create_task(self._work())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)

    def _wrap(self, fn):
        async def handler(msg: Message) -> None:
            try:
                result: BaseModel = await fn(msg.data)
                payload = {"ok": True, **result.model_dump(mode="json")}
            except ValidationError as e:
                payload = {"ok": False, "error": validation_message(e)}
            except ValueError as e:
                payload = {"ok": False, "error": str(e)}
            except Exception as e:  # one bad request never stops the builder
                log.exception("unexpected error")
                payload = {"ok": False, "error": f"internal: {e}"}
            if msg.reply:
                await msg.respond(payload)

        return handler

    # ---- requests ------------------------------------------------------------------------------------

    async def start_build(self, data: dict[str, Any]) -> StartReply:
        req = BuildRequest.model_validate(data)
        coder_name = req.coder or self.default_coder
        coder = self.coders.get(coder_name)
        if coder is None:
            raise ValueError(f"no coder {coder_name!r}; one of {', '.join(self.coders)}")
        if self.workspace.exists(req.name):
            raise ValueError(
                f"a module named {req.name!r} has already been grown (GROWN_DIR/{req.name}); "
                f"if its build failed at deploy, `mctl deploy {req.name}` once the cause is fixed"
            )
        busy = [r for r in [self._current, *self._waiting] if r is not None and r.name == req.name]
        if busy:
            raise ValueError(f"{req.name!r} is already being built ({busy[0].id})")
        if req.name in await self._known_modules():
            raise ValueError(f"a module named {req.name!r} already exists")
        if len(self._waiting) >= self.max_queue:
            raise ValueError(f"the builder is busy: {len(self._waiting)} builds are waiting; try again later")
        try:
            await self.pipeline.repo.ensure()
        except (OSError, RuntimeError) as e:  # e.g. Docker created GROWN_DIR as root before `make up` did
            raise ValueError(f"GROWN_DIR is not writable by the builder ({e}); create it as you: mkdir -p grown") from e
        reason = await coder.ready()
        if reason:
            raise ValueError(f"the {coder_name} coder cannot build now: {reason}")
        record = BuildRecord(
            name=req.name,
            spec=req.spec,
            coder=coder_name,
            cause=req.cause,
            hops=req.hops,
            channel=req.channel,
            thread=req.thread,
        )
        await self._save(record)
        position = len(self._waiting) + (1 if self._current else 0)
        self._waiting.append(record)
        self._wake.set()
        log.info("build %s queued: %s with %s, %d ahead", record.id, record.name, coder_name, position)
        return StartReply(build_id=record.id, position=position)

    async def get(self, data: dict[str, Any]) -> BuildRecord:
        build_id = BuildRef.model_validate(data).build_id
        raw = await self.kv.get(kv_key(PREFIX, build_id))
        if raw is None:
            raise ValueError(f"no build {build_id!r}")
        return BuildRecord.model_validate(raw)

    async def list(self, data: dict[str, Any]) -> BuildList:
        limit = max(1, min(BuildListRequest.model_validate(data).limit, 100))
        keys = sorted(await self.kv.keys(f"{PREFIX}/"), reverse=True)[:limit]  # ids sort by time
        records = await asyncio.gather(*(self.kv.get(k) for k in keys))
        return BuildList(builds=[s for r in records if r and (s := _summary(r))])

    async def list_coders(self, _data: dict[str, Any]) -> CoderList:
        reasons = await asyncio.gather(*(coder.ready() for coder in self.coders.values()))
        coders = [CoderInfo(name=n, ready=r is None, reason=r) for n, r in zip(self.coders, reasons, strict=True)]
        return CoderList(default=self.default_coder, coders=coders)

    async def _known_modules(self) -> set[str]:
        """Every module name in use: deployed (the registry) or with a folder in either root, hand-written ones
        included, so a build never takes one."""
        try:
            reply = await ask(self.bus, "rpc.sys.list", None, ModulesReply, timeout=5)
        except NoAnswer as e:
            raise ValueError("the supervisor is not answering; a build needs it to verify and deploy") from e
        except Refused as e:
            raise ValueError(f"the supervisor could not list modules: {e}") from e
        live = {m.name for m in reply.modules if m.status != "retired"}
        return live | set(reply.folders)  # a retired module's name is free once its folder is gone

    # ---- the worker ----------------------------------------------------------------------------------

    async def recover(self) -> None:
        """After a restart: the running build failed with it, the waiting ones go back in line. Finished records
        beyond the newest KEEP go; one that no longer reads as a BuildRecord is logged and left alone."""
        keys = sorted(await self.kv.keys(f"{PREFIX}/"))
        old = set(keys[: max(0, len(keys) - KEEP)])
        for key in keys:
            raw = await self.kv.get(key)
            if not raw:
                continue
            try:
                record = BuildRecord.model_validate(raw)
            except ValidationError as e:
                log.warning("build record %s unreadable, skipped: %s", key, validation_message(e))
                continue
            if record.status == BuildStatus.BUILDING:
                self._fail(record, Stage.RESTART, "the builder restarted during this build; start it again")
                record.finished = now_iso()
                await self._save(record)
                await self._announce(record, 0.0)
            elif record.status == BuildStatus.QUEUED:
                self._waiting.append(record)
            elif key in old:
                await self.kv.delete(key)
        if self._waiting:
            self._wake.set()
            log.info("%d waiting builds back in line", len(self._waiting))

    async def _work(self) -> None:
        while True:
            while not self._waiting:
                self._wake.clear()
                await self._wake.wait()
            record = self._waiting.pop(0)
            try:
                await self._run(record)
            except Exception:  # the KV or the bus failed around a build: log it, the next one still runs
                log.exception("build %s: could not record or announce it", record.id)
            finally:
                self._current = None

    async def _run(self, record: BuildRecord) -> None:
        self._current = record
        t0 = time.monotonic()
        record.status, record.started = BuildStatus.BUILDING, now_iso()
        deadline = None
        try:
            await self._save(record)
            await self.bus.publish(
                "build.started",
                record.envelope().into(BuildStarted, build_id=record.id, name=record.name, coder=record.coder),
            )
            async with asyncio.timeout(self.build_timeout) as deadline:
                await self.pipeline.run(record, self.coders[record.coder], self._on_round)
            record.status = BuildStatus.DONE
        except PipelineError as e:
            self._fail(record, e.stage, e.error, e.output)
        except CoderUnavailable as e:
            self._fail(record, Stage.CODER, str(e))
        except TimeoutError as e:
            if deadline is None or not deadline.expired():  # from inside (the KV, the bus), not the build's clock
                log.exception("build %s failed", record.id)
                self._fail(record, record.stage or Stage.CODER, f"internal: {type(e).__name__}: {e}")
            else:
                self._fail(record, record.stage or Stage.CODER, f"the build took longer than {self.build_timeout:g}s")
        except Exception as e:
            log.exception("build %s failed", record.id)
            self._fail(record, record.stage or Stage.CODER, f"internal: {e}")
        finally:
            record.finished = now_iso()
        await self._save(record)
        await self._announce(record, round(time.monotonic() - t0, 1))
        log.info("build %s %s: %s", record.id, record.status, record.error or record.commit)

    async def _on_round(self, record: BuildRecord, rnd: Round) -> None:
        await self._save(record)
        await self.bus.publish(
            "build.progress",
            record.envelope().into(
                BuildProgress,
                build_id=record.id,
                name=record.name,
                coder=record.coder,
                round=rnd.n,
                stage=rnd.stage,
                passed=rnd.passed,
            ),
        )

    @staticmethod
    def _fail(record: BuildRecord, stage: Stage, error: str, output: str = "") -> None:
        record.status, record.stage, record.error, record.output = BuildStatus.FAILED, stage, error, output[-4000:]

    async def _announce(self, record: BuildRecord, seconds: float) -> None:
        common = {
            "build_id": record.id,
            "name": record.name,
            "coder": record.coder,
            "rounds": len(record.rounds),
            "seconds": seconds,
            "cost_usd": record.cost_usd,
            "channel": record.channel,
            "thread": record.thread,
        }
        if record.status == BuildStatus.DONE:
            event = record.envelope().into(
                BuildDone, version=record.version, commit=record.commit, image=record.image, **common
            )
            await self.bus.publish("build.done", event)
        else:
            event = record.envelope().into(
                BuildFailed, stage=record.stage, error=record.error, output=record.output, **common
            )
            await self.bus.publish("build.failed", event)

    async def _save(self, record: BuildRecord) -> None:
        await self.kv.put(kv_key(PREFIX, record.id), record.model_dump())


def _summary(raw: dict[str, Any]) -> BuildSummary | None:
    try:
        return BuildRecord.model_validate(raw).summary()
    except ValidationError:
        return None
