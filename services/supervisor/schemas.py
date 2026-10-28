"""What the supervisor answers, where the answer is more than a dict of strings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class VerifyResult(BaseModel):
    """rpc.sys.verify: a module's tests, run in a throwaway container of the image that would ship."""

    name: str
    passed: bool
    stage: Literal["build", "tests"]  # where it stopped: the image did not build, or the tests ran
    exit_code: int | None = None  # pytest's, when the tests ran
    timed_out: bool = False
    output: str  # the tail of the build log or of pytest's output: what a coder fixes from
    seconds: float
