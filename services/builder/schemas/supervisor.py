"""What the builder asks the supervisor, and the answers as it reads them.

    rpc.sys.list      {}           -> ModulesReply   (the supervisor's ModuleList)
    rpc.sys.verify    VerifyCall   -> VerifyReply    (its VerifyResult)
    rpc.sys.deploy    DeployCall   -> DeployReply    (its Deployed)
    rpc.sys.agents    {}           -> AgentsReply    (its AgentList)
    rpc.sys.agent     AgentCall    -> AgentReply     (its AgentRun)

The builder runs in its own image and cannot import the supervisor's schemas: these are its side of the
contract, with only the fields it reads (the rest of an answer is ignored). The supervisor validates each call
again as its own request model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .build import Stage


class ModuleEntry(BaseModel):
    name: str
    status: str


class ModulesReply(BaseModel):
    modules: list[ModuleEntry] = Field(default_factory=list)
    folders: list[str] = Field(default_factory=list)  # every module folder on disk, deployed or not


class VerifyCall(BaseModel):
    name: str
    staging: bool = True  # the build in GROWN_DIR/.staging/<name>


class VerifyReply(BaseModel):
    passed: bool
    stage: Literal[Stage.BUILD, Stage.TESTS]  # the image did not build, or the tests ran
    output: str = ""


class DeployCall(BaseModel):
    name: str


class DeployReply(BaseModel):
    image: str | None = None


class AgentInfo(BaseModel):
    name: str
    ready: bool
    reason: str | None = None


class AgentsReply(BaseModel):
    agents: list[AgentInfo] = Field(default_factory=list)


class AgentCall(BaseModel):
    agent: str
    name: str
    prompt: str
    timeout: float = Field(gt=0)


class AgentReply(BaseModel):
    exit_code: int
    timed_out: bool = False
    output: str = ""
    files: dict[str, str] = Field(default_factory=dict)  # path -> text: the folder as the agent left it
    skipped: list[str] = Field(default_factory=list)  # files it could not bring back: kept as they were
    skipped_more: int = 0  # more of those than were listed: then no file is taken for deleted
    seconds: float = 0.0
