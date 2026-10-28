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
    approved_actuators: str = Field(
        default="", validation_alias="APPROVED_ACTUATORS", description="comma-separated modules allowed to act"
    )
    reconcile_on_start: bool = Field(default=True, validation_alias="RECONCILE_ON_START")

    @field_validator("module_tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        return timezone(v)

    @model_validator(mode="after")
    def _network_defaults(self) -> SupervisorSettings:
        self.module_network = self.module_network or f"{self.stack}-modules"
        self.internet_network = self.internet_network or f"{self.stack}-mesh"
        return self

    @property
    def approved(self) -> set[str]:
        return {s.strip() for s in self.approved_actuators.split(",") if s.strip()}
