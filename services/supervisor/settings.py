"""The supervisor's environment, as one validated model (see mycelium_sdk.settings)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator, model_validator

from mycelium_sdk import ServiceSettings, timezone


class SupervisorSettings(ServiceSettings):
    database_url: str = Field(validation_alias="DATABASE_URL")
    stack: str = Field(
        default="mycelium",
        validation_alias="STACK",
        pattern=r"^[a-z][a-z0-9-]{0,40}$",
        description="namespaces containers, networks, volumes and images (dev / staging / production side by side)",
    )
    module_nats_url: str = Field(
        default="nats://module:module@nats:4222",
        validation_alias="MODULE_NATS_URL",
        description="the bus as modules reach it: the `module` login (services/nats/nats.conf), never NATS_URL's",
    )
    module_network: str | None = Field(
        default=None, validation_alias="MODULE_NETWORK", description="bus only, no internet; default <stack>-modules"
    )
    internet_network: str | None = Field(
        default=None,
        validation_alias="INTERNET_NETWORK",
        description="attached only for permissions.network; default <stack>-mesh",
    )
    modules_dir: Path = Field(default=Path("/workspace/modules"), validation_alias="MODULES_DIR")
    grown_dir: Path | None = Field(
        default=None,
        validation_alias="GROWN_DIR",
        description="the grown modules' own git repo, written by the builder; hand-written ones stay in MODULES_DIR",
    )
    module_tz: str = Field(
        default="UTC", validation_alias="MODULE_TZ", description="TZ in every module: the user's day"
    )
    verify_timeout: float = Field(
        default=300.0, gt=0, validation_alias="VERIFY_TIMEOUT", description="seconds a module's tests may run in verify"
    )
    sdk_dir: Path = Field(default=Path("/workspace/sdk"), validation_alias="SDK_DIR")
    agents_dir: Path = Field(
        default=Path(__file__).resolve().parent / "agent_images",
        validation_alias="AGENTS_DIR",
        description="the coding agents: agents.yaml and an image folder per agent",
    )
    agent_timeout: float = Field(
        default=3600.0, gt=0, validation_alias="AGENT_TIMEOUT", description="seconds one agent run may take, at most"
    )
    approved_actuators: str = Field(
        default="", validation_alias="APPROVED_ACTUATORS", description="comma-separated modules allowed to act"
    )
    reconcile_on_start: bool = Field(default=True, validation_alias="RECONCILE_ON_START")

    @field_validator("module_tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        return timezone(v)

    @model_validator(mode="after")
    def _modules_never_get_the_core_login(self) -> SupervisorSettings:
        if _login(self.module_nats_url) == _login(self.nats_url):
            raise ValueError(
                "MODULE_NATS_URL has the same login as NATS_URL: every module would hold the services' login; "
                "give it the `module` user (services/nats/nats.conf)"
            )
        return self

    @model_validator(mode="after")
    def _network_defaults(self) -> SupervisorSettings:
        self.module_network = self.module_network or f"{self.stack}-modules"
        self.internet_network = self.internet_network or f"{self.stack}-mesh"
        return self

    @property
    def approved(self) -> set[str]:
        return {s.strip() for s in self.approved_actuators.split(",") if s.strip()}


def _login(url: str) -> str:
    """The user part of nats://user:password@host:port ('' when there is none)."""
    rest = url.split("://", 1)[-1]
    return rest.split("@", 1)[0].split(":", 1)[0] if "@" in rest else ""
