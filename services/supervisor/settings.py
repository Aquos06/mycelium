"""The supervisor's environment, as one validated model (see mycelium_sdk.settings)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator

from mycelium_sdk import ServiceSettings


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
    sdk_dir: Path = Field(default=Path("/workspace/sdk"), validation_alias="SDK_DIR")
    approved_actuators: str = Field(
        default="", validation_alias="APPROVED_ACTUATORS", description="comma-separated modules allowed to act"
    )
    reconcile_on_start: bool = Field(default=True, validation_alias="RECONCILE_ON_START")

    @model_validator(mode="after")
    def _network_defaults(self) -> SupervisorSettings:
        self.module_network = self.module_network or f"{self.stack}-modules"
        self.internet_network = self.internet_network or f"{self.stack}-mesh"
        return self

    @property
    def approved(self) -> set[str]:
        return {s.strip() for s in self.approved_actuators.split(",") if s.strip()}
