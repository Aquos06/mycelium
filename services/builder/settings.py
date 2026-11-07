"""The builder's environment, as one validated model (see mycelium_sdk.settings)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from mycelium_sdk import ServiceSettings


class BuilderSettings(ServiceSettings):
    grown_dir: Path = Field(
        default=Path("/workspace/grown"),
        validation_alias="GROWN_DIR",
        description="grown modules: a git repo the builder writes, one commit per build; builds wait in .staging/",
    )
    template_dir: Path = Field(default=Path("/workspace/template"), validation_alias="TEMPLATE_DIR")
    example_dir: Path = Field(
        default=Path("/workspace/example"),
        validation_alias="EXAMPLE_DIR",
        description="the hand-written module every coder is shown as the example (hello)",
    )
    coder: str = Field(
        default="mycelium",
        validation_alias="BUILDER_CODER",
        description="the first default coder: a choice in Settings → Builder (rpc.build.default) replaces it",
    )
    max_rounds: int = Field(
        default=6, ge=1, le=20, validation_alias="BUILD_MAX_ROUNDS", description="coder -> checks -> verify passes"
    )
    build_timeout: float = Field(
        default=3600.0, gt=0, validation_alias="BUILD_TIMEOUT", description="seconds for a whole build"
    )
    max_queue: int = Field(default=5, ge=1, validation_alias="BUILD_MAX_QUEUE", description="builds waiting at most")
    verify_timeout: float = Field(
        default=900.0,
        gt=0,
        validation_alias="BUILD_VERIFY_TIMEOUT",
        description="seconds to wait for rpc.sys.verify: the image build, the tests, a supervisor still starting",
    )
    deploy_timeout: float = Field(default=600.0, gt=0, validation_alias="BUILD_DEPLOY_TIMEOUT")
    agents: str = Field(
        default="opencode,claude_code,codex,aider",
        validation_alias="BUILDER_AGENTS",
        description="comma-separated coding agents a build may use (the supervisor's agents.yaml has their recipes)",
    )
    agent_timeout: float = Field(
        default=1800.0, gt=0, validation_alias="AGENT_ROUND_TIMEOUT", description="seconds for one agent round"
    )
    # our coder (BUILDER_CODER=mycelium): the gateway's `coder` slot
    coder_slot: str = Field(default="coder", validation_alias="CODER_SLOT")
    coder_llm_timeout: float = Field(
        default=600.0,
        gt=0,
        validation_alias="CODER_LLM_TIMEOUT",
        description="seconds per model call: a local reasoning model writing a whole file is slow",
    )
    coder_max_calls: int = Field(default=40, ge=1, validation_alias="CODER_MAX_CALLS", description="per build")
    coder_max_usd: float = Field(
        default=2.0,
        ge=0,
        validation_alias="CODER_MAX_USD",
        description="per build; a local model costs nothing; 0 lets no paid call past the first",
    )

    @property
    def agent_names(self) -> list[str]:
        return [a.strip() for a in self.agents.split(",") if a.strip()]
