"""One build, start to end: the rounds, then promote, commit and deploy.

    scaffold GROWN_DIR/.staging/<name> from template/, with SPEC.md
              (a change: a copy of GROWN_DIR/<name> as it is, its SPEC.md ending with the change)
    round n:  coder writes -> tidy (the builder's files back, strays out) -> pin the manifest -> checks
              -> rpc.sys.verify (the image builds, the tests pass in the sealed container)
              a failure becomes the next round's feedback; a pass ends the rounds
    snapshot  a change: rpc.sys.snapshot copies the module's data before the new version can touch it
    promote   .staging/<name> -> <name>, one commit in GROWN_DIR, tagged <name>-v<version>
    deploy    rpc.sys.deploy (the same data volume: a change keeps the module's data)

A change that fails before deploy leaves the module running as it was: nothing of it reaches GROWN_DIR/<name>.

Every coder is judged the same way; none of them grades its own work. The record is updated as it goes: each step
it enters (`stage`, `since`) is handed to `on_stage`, and each round that ends, with its one-line summary, to
`on_round`, to be stored and announced.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from mycelium_sdk import Bus, ManifestError, NoAnswer, Refused, ask, load_manifest, now_iso

from .checks import check_files, pin_manifest
from .coders.base import Coder, CoderError, CoderUnavailable
from .prompts import Brief
from .repo import GrownRepo
from .schemas import (
    BuildMode,
    BuildRecord,
    CoderContext,
    DeployCall,
    DeployReply,
    Feedback,
    Round,
    SnapshotCall,
    SnapshotReply,
    Stage,
    VerifyCall,
    VerifyReply,
)
from .summary import round_summary
from .workspace import CONTRACT, Workspace

VERSION = "0.1.0"  # a new module; a change bumps the minor version (next_version)

OnRound = Callable[[BuildRecord, Round], Awaitable[None]]
OnStage = Callable[[BuildRecord, int], Awaitable[None]]  # the record as it enters a stage, and the round it is in


async def _quiet(_record: BuildRecord, _round: int) -> None:
    return None


R = TypeVar("R", bound=BaseModel)


def next_version(base: str) -> str:
    """0.1.0 -> 0.2.0: a change build's version. A version that does not read as x.y.z starts again at 0.2.0."""
    parts = base.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{int(parts[1]) + 1}.0"
    return "0.2.0"


def change_spec(spec: str, change: str, version: str) -> str:
    """SPEC.md for a change build: what the module was built from, and the change as its last section, so the
    file keeps every change in order and the next one starts from all of it."""
    base = spec.strip() or "(no SPEC.md was kept for this module: its code is what it does)"
    return f"{base}\n\n## Change in v{version}\n\n{change.strip()}\n"


class PipelineError(Exception):
    """The build stops here: where, why, and the output that shows it."""

    def __init__(self, stage: Stage, error: str, output: str = "") -> None:
        super().__init__(error)
        self.stage = stage
        self.error = error
        self.output = output


class Pipeline:
    def __init__(
        self,
        bus: Bus,
        workspace: Workspace,
        repo: GrownRepo,
        brief: Brief,
        max_rounds: int = 6,
        verify_timeout: float = 900.0,
        deploy_timeout: float = 600.0,
    ) -> None:
        self.bus = bus
        self.workspace = workspace
        self.repo = repo
        self.brief = brief
        self.max_rounds = max_rounds
        self.verify_timeout = verify_timeout
        self.deploy_timeout = deploy_timeout

    async def run(self, record: BuildRecord, coder: Coder, on_round: OnRound, on_stage: OnStage = _quiet) -> None:
        """Fills the record's version, commit and image, or raises PipelineError (CoderUnavailable passes up)."""

        async def enter(stage: Stage, n: int) -> None:
            record.stage, record.since = stage, now_iso()
            await on_stage(record, n)

        name = record.name
        change = record.mode == BuildMode.CHANGE
        version = next_version(record.base_version or VERSION) if change else VERSION
        start = self.workspace.start_change if change else self.workspace.start
        d = await asyncio.to_thread(start, name, record.spec)
        fresh, feedback = not change, None
        for n in range(1, self.max_rounds + 1):
            t0 = time.monotonic()
            await enter(Stage.CODER, n)
            ctx = CoderContext(
                build_id=record.id,
                name=name,
                spec=record.spec,
                dir=d,
                round=n,
                fresh=fresh,
                change=record.change,
                feedback=feedback,
                brief=self.brief,
            )
            try:
                res = await coder.write(ctx)
            except CoderUnavailable as e:  # the build stops, but this round's spend is kept
                rnd = Round(n=n, stage=Stage.CODER, output=str(e), calls=e.calls, cost_usd=e.cost_usd)
                await self._end(record, rnd, t0, on_round)
                raise
            except CoderError as e:
                rnd = Round(n=n, stage=Stage.CODER, output=str(e), calls=e.calls, cost_usd=e.cost_usd)
                if feedback is not None and feedback.stage != Stage.CODER:  # what still has to be fixed stays in view
                    feedback = Feedback(
                        stage=feedback.stage,
                        output=f"{feedback.output}\n\n(the next round could not write its fix: {e})",
                    )
                else:
                    feedback = Feedback(stage=Stage.CODER, output=str(e))
                await self._end(record, rnd, t0, on_round)
                continue
            fresh = False
            record.model = res.model or record.model
            rnd = Round(n=n, stage=Stage.CHECKS, note=res.note, log=res.log, calls=res.calls, cost_usd=res.cost_usd)

            await enter(Stage.CHECKS, n)
            removed = await asyncio.to_thread(self.workspace.tidy, name, record.spec)
            if removed:
                rnd.note = f"{rnd.note} (removed {', '.join(removed)})".strip()
            _, problems = pin_manifest(d, name, version)
            files = {k: v for k, v in self.workspace.files(name).items() if k != CONTRACT}
            problems += check_files(d, files)
            if problems:
                rnd.output = "\n".join(problems)
                feedback = Feedback(stage=Stage.CHECKS, output=rnd.output)
                await self._end(record, rnd, t0, on_round)
                continue

            await enter(Stage.VERIFY, n)
            result = await self._ask(
                "rpc.sys.verify", VerifyCall(name=name), VerifyReply, self.verify_timeout, Stage.VERIFY
            )
            rnd.stage, rnd.passed, rnd.output = result.stage, result.passed, result.output
            await self._end(record, rnd, t0, on_round)
            if rnd.passed:
                break
            feedback = Feedback(stage=rnd.stage, output=rnd.output)
        else:
            last = record.rounds[-1]
            raise PipelineError(last.stage, f"no working module after {self.max_rounds} rounds", last.output)

        if change:  # before anything of the new version is in GROWN_DIR: a failure here leaves the old one as it was
            await enter(Stage.SNAPSHOT, len(record.rounds))
            call = SnapshotCall(name=name, label=f"v{record.base_version}-{record.id}")
            try:
                snap = await self._ask("rpc.sys.snapshot", call, SnapshotReply, self.deploy_timeout, Stage.SNAPSHOT)
            except PipelineError as e:  # no copy, no change: the data is what Hansen cannot get back
                e.error += f". Nothing was changed: {name} still runs as v{record.base_version}"
                raise
            record.snapshot = snap.volume

        await enter(Stage.PROMOTE, len(record.rounds))
        try:
            purpose = load_manifest(d / "manifest.yaml").purpose
            await asyncio.to_thread(self.workspace.promote, name, change)
        except (OSError, ManifestError) as e:
            raise PipelineError(Stage.PROMOTE, str(e)) from e
        what = f"change from v{record.base_version}: {record.change.strip()}\n\n" if change else ""
        kept = f", data copied to {record.snapshot} first" if record.snapshot else ""
        message = (
            f"{name} v{version}\n\n{purpose}\n\n{what}"
            f"build {record.id}, coder {record.coder}{f' ({record.model})' if record.model else ''}, "
            f"{len(record.rounds)} round{'s' if len(record.rounds) != 1 else ''}{kept}"
        )
        try:
            record.commit = await self.repo.commit(name, version, message)
        except (OSError, RuntimeError) as e:  # back to staging: an uncommitted module never sits in GROWN_DIR
            await asyncio.to_thread(self.workspace.demote, name)
            raise PipelineError(Stage.PROMOTE, f"could not commit it: {e}") from e
        await asyncio.to_thread(self.workspace.settle, name)
        record.version = version

        await enter(Stage.DEPLOY, len(record.rounds))
        try:
            reply = await self._ask(
                "rpc.sys.deploy", DeployCall(name=name), DeployReply, self.deploy_timeout, Stage.DEPLOY
            )
        except PipelineError as e:  # the module is built and committed: only the deploy is left to do
            e.error += f". It is committed ({record.commit}): `mctl deploy {name}` once that is fixed"
            if change:
                e.error += (
                    f"; v{record.base_version} is tagged {name}-v{record.base_version}"
                    f"{f' and its data is in {record.snapshot}' if record.snapshot else ''}"
                )
            raise
        record.image = reply.image
        record.stage = None

    async def _ask(self, subject: str, call: BaseModel, reply: type[R], timeout: float, stage: Stage) -> R:
        try:
            return await ask(self.bus, subject, call, reply, timeout)
        except NoAnswer as e:
            raise PipelineError(stage, f"the supervisor did not answer {subject} within {timeout:g}s") from e
        except Refused as e:
            raise PipelineError(stage, f"{subject}: {e}") from e

    @staticmethod
    async def _end(record: BuildRecord, rnd: Round, t0: float, on_round: OnRound) -> None:
        rnd.seconds = round(time.monotonic() - t0, 1)
        rnd.summary = round_summary(rnd)
        record.rounds.append(rnd)
        record.cost_usd = round(record.cost_usd + rnd.cost_usd, 6)
        await on_round(record, rnd)
