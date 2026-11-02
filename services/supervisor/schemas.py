"""rpc.sys.* requests and replies, and the records behind them.

    rpc.sys.deploy   ModuleRef        -> Deployed
    rpc.sys.verify   VerifyRequest    -> VerifyResult
    rpc.sys.agent    AgentRequest     -> AgentRun
    rpc.sys.agents   {}               -> AgentList
    rpc.sys.stop     ModuleRef        -> Stopped
    rpc.sys.logs     LogsRequest      -> Logs
    rpc.sys.list     {}               -> ModuleList
    rpc.sys.health   {}               -> HealthReport

The handler adds ok=true; errors are {"ok": false, "error": "<field>: <message>"}.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from mycelium_sdk.manifest import NAME_RE


def _module_name(v: str) -> str:
    if not NAME_RE.match(v):
        raise ValueError(f"invalid module name: {v!r}")
    return v


ModuleName = Annotated[str, AfterValidator(_module_name)]  # also keeps `.staging` and `../x` out of every path


class ModuleStatus(StrEnum):
    """A registry row's status: what the supervisor last did with the module."""

    BUILDING = "building"
    RUNNING = "running"
    FAILED = "failed"
    STOPPED = "stopped"
    RETIRED = "retired"  # its folder is gone; reconcile no longer brings it back


class VerifyStage(StrEnum):
    """Where a verify stopped: the image did not build, or the tests ran."""

    BUILD = "build"
    TESTS = "tests"


# ---- requests ------------------------------------------------------------------------------------


class ModuleRef(BaseModel):
    """rpc.sys.deploy, rpc.sys.stop: one module, by name."""

    name: ModuleName


class VerifyRequest(BaseModel):
    name: ModuleName
    staging: bool = False  # the build in GROWN_DIR/.staging/<name>, not the deployed folder


class AgentRequest(BaseModel):
    agent: str
    name: ModuleName  # a staged build: the agent works on a copy of it
    prompt: str
    timeout: float | None = Field(default=None, gt=0)  # None: AGENT_TIMEOUT; kept between 10s and it

    @field_validator("prompt")
    @classmethod
    def _prompt(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt is required")
        return v


class LogsRequest(BaseModel):
    name: ModuleName
    tail: int = 100  # kept between 1 and 2000


# ---- replies -------------------------------------------------------------------------------------


class Deployed(BaseModel):
    name: str
    image: str
    status: str  # the container's


class Stopped(BaseModel):
    name: str
    stopped: bool  # False: there was no container to stop


class Logs(BaseModel):
    name: str
    logs: str


class VerifyResult(BaseModel):
    """rpc.sys.verify: a module's tests, run in a throwaway container of the image that would ship."""

    name: str
    passed: bool
    stage: VerifyStage
    exit_code: int | None = None  # pytest's, when the tests ran
    timed_out: bool = False
    output: str  # the tail of the build log or of pytest's output: what a coder fixes from
    seconds: float


class AgentRecipe(BaseModel):
    """One coding agent in agent_images/agents.yaml: how its container is set up (its image: agent_images/<name>/)."""

    description: str
    env: dict[str, str] = Field(default_factory=dict)  # the agent's variable -> the supervisor's variable
    needs: list[str] = Field(default_factory=list)  # supervisor variables that must be set for it to run
    memory_mb: int = Field(default=2048, ge=256, le=16384)
    cpus: float = Field(default=2.0, gt=0, le=16)


class AgentInfo(BaseModel):
    """rpc.sys.agents, one per agent: can it take a build now, and if not, why."""

    name: str
    description: str
    ready: bool
    reason: str | None = None


class AgentList(BaseModel):
    agents: list[AgentInfo] = Field(default_factory=list)


class AgentRun(BaseModel):
    """rpc.sys.agent: one agent run on a staged build. `files` is the folder as the agent left it."""

    agent: str
    name: str
    exit_code: int
    timed_out: bool = False
    output: str  # the tail of what the agent printed, keys redacted
    files: dict[str, str] = Field(default_factory=dict)  # path -> text, only small text files
    skipped: list[str] = Field(default_factory=list)  # text files it left that were too big or too many to bring
    skipped_more: int = 0  # more of those than were listed: the builder must not take a missing file for deleted
    seconds: float


class Unpacked(BaseModel):
    """The folder as an agent left it (agents.unpack): small text files, and the ones there that did not come back."""

    files: dict[str, str] = Field(default_factory=dict)  # path -> text
    skipped: list[str] = Field(default_factory=list)  # the first SKIPPED_MAX left out, top of the folder first
    skipped_more: int = 0  # left out and not listed (a venv, a node_modules by another name)


class ModuleRecord(BaseModel):
    """One row of the registry: a module the supervisor deployed, and the manifest it was deployed with."""

    name: str
    version: str
    status: ModuleStatus
    image: str | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)  # as it was then: an old row may not fit today's Manifest


class ModuleRow(ModuleRecord):
    container: str | None = None  # the container's status now; None: there is none


class ModuleList(BaseModel):
    """rpc.sys.list: the registry, and every module folder on disk in either root (names a build may not take)."""

    modules: list[ModuleRow] = Field(default_factory=list)
    folders: list[str] = Field(default_factory=list)


class ModuleHealth(BaseModel):
    """What a module answered to rpc.mod.<name>.health, kept as it came (its name, version, ...); or
    {ok: false, status} for a container that is not running, {ok: false, error} for one that did not answer."""

    model_config = ConfigDict(extra="allow")

    ok: bool


class HealthReport(BaseModel):
    modules: dict[str, ModuleHealth] = Field(default_factory=dict)
