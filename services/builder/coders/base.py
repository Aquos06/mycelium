"""What a coder is: given a build's folder and what went wrong last round, it writes the files.

The builder runs the rounds and judges every coder the same way (checks, then the supervisor's sealed
verify); a coder only writes. Ours (mycelium.py) writes through the gateway's `coder` slot; a coding agent
(agent.py) works in a container the supervisor runs.
"""

from __future__ import annotations

from typing import Protocol

from ..schemas import CoderContext, CoderResult


class CoderError(Exception):
    """This round's writing failed (the model never produced a valid call): the next round tries again."""

    def __init__(self, message: str, calls: int = 0, cost_usd: float = 0.0) -> None:
        super().__init__(message)
        self.calls = calls
        self.cost_usd = cost_usd


class CoderUnavailable(Exception):
    """The coder cannot work at all (its model does not answer, a cap is spent): the build stops here."""

    def __init__(self, message: str, calls: int = 0, cost_usd: float = 0.0) -> None:
        super().__init__(message)
        self.calls = calls
        self.cost_usd = cost_usd


class Coder(Protocol):
    name: str

    async def ready(self) -> str | None:
        """None when it can take a build, else the reason it cannot (shown to whoever asked)."""
        ...

    async def write(self, ctx: CoderContext) -> CoderResult: ...
