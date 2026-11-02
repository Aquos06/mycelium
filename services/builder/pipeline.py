"""One build, start to end: the rounds, then promote, commit and deploy.

    scaffold GROWN_DIR/.staging/<name> from template/, with SPEC.md
    round n:  coder writes -> tidy (the builder's files back, strays out) -> pin the manifest -> checks
              -> rpc.sys.verify (the image builds, the tests pass in the sealed container)
              a failure becomes the next round's feedback; a pass ends the rounds
    promote   .staging/<name> -> <name>, one commit in GROWN_DIR, tagged <name>-v<version>
    deploy    rpc.sys.deploy

Every coder is judged the same way; none of them grades its own work. The record is updated as it goes
(`stage` says where the build is), and each round is handed to `on_round` to be stored and announced.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from mycelium_sdk import Bus, ManifestError, NoAnswer, Refused, ask, load_manifest

from .checks import check_files, pin_manifest
from .coders.base import Coder, CoderError, CoderUnavailable
from .prompts import Brief
from .repo import GrownRepo
from .schemas import (
    BuildRecord,
    CoderContext,
    DeployCall,
    DeployReply,
    Feedback,
    Round,
    Stage,
    VerifyCall,
    VerifyReply,
)
from .workspace import CONTRACT, Workspace

VERSION = "0.1.0"  # a new module; change builds bump it

OnRound = Callable[[BuildRecord, Round], Awaitable[None]]
R = TypeVar("R", bound=BaseModel)


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

    async def run(self, record: BuildRecord, coder: Coder, on_round: OnRound) -> None:
        """Fills the record's version, commit and image, or raises PipelineError (CoderUnavailable passes up)."""
        name = record.name
        d = await asyncio.to_thread(self.workspace.start, name, record.spec)
        fresh, feedback = True, None
        for n in range(1, self.max_rounds + 1):
            t0 = time.monotonic()
            record.stage = Stage.CODER
            ctx = CoderContext(
                build_id=record.id,
                name=name,
                spec=record.spec,
                dir=d,
                round=n,
                fresh=fresh,
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

            record.stage = Stage.CHECKS
            removed = await asyncio.to_thread(self.workspace.tidy, name, record.spec)
            if removed:
                rnd.note = f"{rnd.note} (removed {', '.join(removed)})".strip()
            _, problems = pin_manifest(d, name, VERSION)
            files = {k: v for k, v in self.workspace.files(name).items() if k != CONTRACT}
            problems += check_files(d, files)
            if problems:
                rnd.output = "\n".join(problems)
                feedback = Feedback(stage=Stage.CHECKS, output=rnd.output)
                await self._end(record, rnd, t0, on_round)
                continue

            record.stage = Stage.VERIFY
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

        record.stage = Stage.PROMOTE
        try:
            purpose = load_manifest(d / "manifest.yaml").purpose
            await asyncio.to_thread(self.workspace.promote, name)
        except (OSError, ManifestError) as e:
            raise PipelineError(Stage.PROMOTE, str(e)) from e
        message = (
            f"{name} v{VERSION}\n\n{purpose}\n\n"
            f"build {record.id}, coder {record.coder}{f' ({record.model})' if record.model else ''}, "
            f"{len(record.rounds)} round{'s' if len(record.rounds) != 1 else ''}"
        )
        try:
            record.commit = await self.repo.commit(name, VERSION, message)
        except (OSError, RuntimeError) as e:  # back to staging: an uncommitted module never sits in GROWN_DIR
            await asyncio.to_thread(self.workspace.demote, name)
            raise PipelineError(Stage.PROMOTE, f"could not commit it: {e}") from e
        record.version = VERSION

        record.stage = Stage.DEPLOY
        try:
            reply = await self._ask(
                "rpc.sys.deploy", DeployCall(name=name), DeployReply, self.deploy_timeout, Stage.DEPLOY
            )
        except PipelineError as e:  # the module is built and committed: only the deploy is left to do
            e.error += f". It is committed ({record.commit}): `mctl deploy {name}` once that is fixed"
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
        record.rounds.append(rnd)
        record.cost_usd = round(record.cost_usd + rnd.cost_usd, 6)
        await on_round(record, rnd)
