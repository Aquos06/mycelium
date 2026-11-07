"""The builder on the bus.

    rpc.build.start   BuildRequest       -> StartReply (a spec: a new module; a change: one the builder grew)
    rpc.build.get     BuildRef           -> BuildRecord
    rpc.build.list    BuildListRequest   -> BuildList (newest first)
    rpc.build.coders  {}                 -> CoderList
    rpc.build.default CoderChoice        -> CoderList
Each handler returns a model; it goes back as Answer.of(it) ({"ok": true, ...}), or Refusal ({"ok": false, "error"}).
Events, each with the thread that asked (channel, thread):
    build.started / build.stage (each step it enters) / build.progress (each round's end) / build.done / build.failed
    build.stage, build.done and build.failed carry every finished round in a line (`history`) and a `seq`
    build.coder: the default coder changed (CoderChosen)

A build starts by request, not by event: an event would vanish while the builder is down (core NATS has no
durable consumers here), a request gets an answer or an error. A name that exists (a change: one the builder
did not grow), a full queue, a coder that cannot work or a supervisor that does not answer is refused at once,
with the reason. One build runs at a
time; the rest wait in line. Records live in the `builder` KV bucket. A restart fails the build that was
running (its folder is half written) and puts the waiting ones back in line.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from mycelium_sdk import (
    KV,
    Answer,
    Bus,
    ManifestError,
    Message,
    NoAnswer,
    Refusal,
    Refused,
    ask,
    kv_key,
    load_manifest,
    now_iso,
    validation_message,
)
from mycelium_sdk.bus import Handler

from .coders import Coder, CoderUnavailable
from .pipeline import Pipeline, PipelineError, change_spec, next_version
from .schemas import (
    SPEC_MAX,
    BuildDone,
    BuildEvent,
    BuildFailed,
    BuildList,
    BuildListRequest,
    BuildMode,
    BuildProgress,
    BuildRecord,
    BuildRef,
    BuildRequest,
    BuildStage,
    BuildStarted,
    BuildStatus,
    BuildSummary,
    CoderChoice,
    CoderChosen,
    CoderInfo,
    CoderList,
    CoderSetting,
    ModulesReply,
    Round,
    Stage,
    StartReply,
)
from .workspace import Workspace

log = logging.getLogger("mycelium.builder")

PREFIX = "builds"
CODER_KEY = kv_key("settings", "coder")  # the chosen default; BUILDER_CODER until there is one
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
        self.seed = default_coder  # BUILDER_CODER
        self.default_coder = default_coder
        self.max_queue = max_queue
        self.build_timeout = build_timeout
        self._waiting: list[BuildRecord] = []
        self._current: BuildRecord | None = None
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None

    async def start(self) -> None:
        await self.recover()  # before the first request: a build started now must not be recovered twice
        await self._load_choice()
        await self.bus.subscribe("rpc.build.start", self._wrap(self.start_build, BuildRequest), queue="builder")
        await self.bus.subscribe("rpc.build.get", self._wrap(self.get, BuildRef), queue="builder")
        await self.bus.subscribe("rpc.build.list", self._wrap(self.list, BuildListRequest), queue="builder")
        await self.bus.subscribe("rpc.build.coders", self._wrap(self.list_coders), queue="builder")
        await self.bus.subscribe("rpc.build.default", self._wrap(self.choose_coder, CoderChoice), queue="builder")
        self._worker = asyncio.create_task(self._work())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)

    def _wrap(self, fn: Callable[..., Awaitable[BaseModel]], request: type[BaseModel] | None = None) -> Handler:
        """A bus handler for `fn`: the message read as `request` (none: `fn` takes nothing), its result answered."""

        async def handler(msg: Message) -> None:
            reply: Answer | Refusal
            try:
                reply = Answer.of(await (fn(request.model_validate(msg.data)) if request else fn()))
            except ValidationError as e:
                reply = Refusal(error=validation_message(e))
            except ValueError as e:
                reply = Refusal(error=str(e))
            except Exception as e:  # one bad request never stops the builder
                log.exception("unexpected error")
                reply = Refusal(error=f"internal: {e}")
            if msg.reply:
                await msg.respond(reply)

        return handler

    # ---- requests ------------------------------------------------------------------------------------

    async def start_build(self, req: BuildRequest) -> StartReply:
        coder_name = req.coder or self.default_coder
        coder = self.coders.get(coder_name)
        if coder is None:
            raise ValueError(f"no coder {coder_name!r}; one of {', '.join(self.coders)}")
        busy = [r for r in [self._current, *self._waiting] if r is not None and r.name == req.name]
        if busy:
            raise ValueError(f"{req.name!r} is already being built ({busy[0].id})")
        if req.is_change:
            record = await self._change(req, coder_name)
        else:
            if self.workspace.exists(req.name):
                raise ValueError(
                    f"a module named {req.name!r} has already been grown (GROWN_DIR/{req.name}); to change it, send "
                    f"a `change` instead of a spec. If its build failed at deploy, `mctl deploy {req.name}` once the "
                    "cause is fixed"
                )
            if req.name in await self._known_modules():
                raise ValueError(f"a module named {req.name!r} already exists")
            record = BuildRecord(name=req.name, spec=req.spec, coder=coder_name)
        if len(self._waiting) >= self.max_queue:
            raise ValueError(f"the builder is busy: {len(self._waiting)} builds are waiting; try again later")
        try:
            await self.pipeline.repo.ensure()
        except (OSError, RuntimeError) as e:  # e.g. Docker created GROWN_DIR as root before `make up` did
            raise ValueError(f"GROWN_DIR is not writable by the builder ({e}); create it as you: mkdir -p grown") from e
        reason = await coder.ready()
        if reason:
            raise ValueError(f"the {coder_name} coder cannot build now: {reason}")
        record.cause, record.hops, record.channel, record.thread = req.cause, req.hops, req.channel, req.thread
        await self._save(record)
        position = len(self._waiting) + (1 if self._current else 0)
        self._waiting.append(record)
        self._wake.set()
        log.info(
            "build %s queued: %s (%s) with %s, %d ahead", record.id, record.name, record.mode, coder_name, position
        )
        return StartReply(build_id=record.id, position=position)

    async def _change(self, req: BuildRequest, coder: str) -> BuildRecord:
        """A change to a module the builder grew: its folder in GROWN_DIR, its version, its spec with the change."""
        name = req.name
        if not self.workspace.exists(name):
            here = " (it is hand-written, in modules/)" if name in await self._known_modules() else ""
            raise ValueError(
                f"there is no grown module {name!r} to change{here}: the builder changes only the modules it grew, "
                "in GROWN_DIR"
            )
        await self._known_modules()  # the supervisor answers: a change needs it to verify, copy the data, deploy
        try:
            base = load_manifest(self.workspace.module(name) / "manifest.yaml").version
        except (OSError, ManifestError) as e:
            raise ValueError(f"{name}'s manifest does not read ({e}); it cannot be changed as it is") from e
        spec = change_spec(self.workspace.spec(name), req.change, next_version(base))
        if len(spec) > SPEC_MAX:
            raise ValueError(
                f"{name}'s SPEC.md with this change is {len(spec)} characters, over {SPEC_MAX}: too many changes in "
                "one module; grow a new one from a spec instead"
            )
        return BuildRecord(
            name=name,
            spec=spec,
            coder=coder,
            mode=BuildMode.CHANGE,
            change=req.change,
            base_version=base,
            base_commit=await self.pipeline.repo.last_commit(name),
        )

    async def get(self, ref: BuildRef) -> BuildRecord:
        build_id = ref.build_id
        raw = await self.kv.get(kv_key(PREFIX, build_id))
        if raw is None:
            raise ValueError(f"no build {build_id!r}")
        return BuildRecord.model_validate(raw)

    async def list(self, req: BuildListRequest) -> BuildList:
        limit = max(1, min(req.limit, 100))
        keys = sorted(await self.kv.keys(f"{PREFIX}/"), reverse=True)[:limit]  # ids sort by time
        records = await asyncio.gather(*(self.kv.get(k) for k in keys))
        return BuildList(builds=[s for r in records if r and (s := _summary(r))])

    async def list_coders(self) -> CoderList:
        coders = await asyncio.gather(*(self._info(name, coder) for name, coder in self.coders.items()))
        return CoderList(default=self.default_coder, seed=self.seed, coders=list(coders))

    async def choose_coder(self, req: CoderChoice) -> CoderList:
        if req.coder not in self.coders:
            raise ValueError(f"no coder {req.coder!r}; one of {', '.join(self.coders)}")
        if req.coder == self.seed:  # back to BUILDER_CODER: kept nowhere, so a later change to it takes effect
            await self.kv.delete(CODER_KEY)
        else:
            await self.kv.put(CODER_KEY, CoderSetting(coder=req.coder))
        previous, self.default_coder = self.default_coder, req.coder
        if req.coder != previous:
            log.info("default coder: %s (was %s)", req.coder, previous)
            await self.bus.publish("build.coder", CoderChosen(coder=req.coder, previous=previous, seed=self.seed))
        return await self.list_coders()

    @staticmethod
    async def _info(name: str, coder: Coder) -> CoderInfo:
        reason, description = await asyncio.gather(coder.ready(), coder.describe())
        return CoderInfo(name=name, description=description, ready=reason is None, reason=reason)

    async def _load_choice(self) -> None:
        """The default chosen before a restart, unless that coder is no longer configured (BUILDER_AGENTS)."""
        raw = await self.kv.get(CODER_KEY)
        if not raw:
            return
        try:
            choice = CoderSetting.model_validate(raw)
        except ValidationError as e:
            log.warning("the chosen coder is unreadable, keeping BUILDER_CODER: %s", validation_message(e))
            return
        if choice.coder in self.coders:
            self.default_coder = choice.coder
            if choice.coder != self.seed:
                log.info(
                    "default coder %s, chosen in Settings → Builder; BUILDER_CODER=%s is not used",
                    choice.coder,
                    self.seed,
                )
        else:
            log.warning(
                "the chosen coder %r is not configured any more, keeping BUILDER_CODER=%s", choice.coder, self.seed
            )

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
                await self._end(record, 0.0)
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
            await self.bus.publish("build.started", BuildStarted.of(record, self.pipeline.max_rounds))
            async with asyncio.timeout(self.build_timeout) as deadline:
                await self.pipeline.run(record, self.coders[record.coder], self._on_round, self._on_stage)
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
        await self._end(record, round(time.monotonic() - t0, 1))
        log.info("build %s %s: %s", record.id, record.status, record.error or record.commit)

    async def _on_stage(self, record: BuildRecord, n: int) -> None:
        """A step begins: stored (rpc.build.get says where it is) and announced with the rounds so far."""
        record.seq += 1
        await self._as_it_goes(record, "build.stage", BuildStage.of(record, n, self.pipeline.max_rounds))

    async def _on_round(self, record: BuildRecord, rnd: Round) -> None:
        await self._as_it_goes(record, "build.progress", BuildProgress.of(record, rnd, self.pipeline.max_rounds))

    async def _as_it_goes(self, record: BuildRecord, subject: str, event: BuildEvent) -> None:
        """Stored and announced during the build, but never at its cost: the KV or the bus failing for a moment
        must not stop a build that works (at deploy, one already committed). Its end is stored and told anyway."""
        try:
            await self._save(record)
            await self.bus.publish(subject, event)
        except Exception as e:
            log.warning("build %s: could not store or announce %s: %s", record.id, subject, e)

    @staticmethod
    def _fail(record: BuildRecord, stage: Stage, error: str, output: str = "") -> None:
        record.status, record.stage, record.error, record.output = BuildStatus.FAILED, stage, error, output[-4000:]

    async def _end(self, record: BuildRecord, seconds: float) -> None:
        """Stored as it ended, then told: build.done or build.failed, with the same seq the record keeps."""
        record.finished, record.since = now_iso(), None
        record.seq += 1
        await self._save(record)
        if record.status == BuildStatus.DONE:
            await self.bus.publish("build.done", BuildDone.of(record, seconds))
        else:
            await self.bus.publish("build.failed", BuildFailed.of(record, seconds))

    async def _save(self, record: BuildRecord) -> None:
        await self.kv.put(kv_key(PREFIX, record.id), record)


def _summary(raw: dict[str, Any]) -> BuildSummary | None:
    try:
        return BuildRecord.model_validate(raw).summary()
    except ValidationError:
        return None
