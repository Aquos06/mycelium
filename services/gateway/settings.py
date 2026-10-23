"""The gateway's environment, as one validated model (see mycelium_sdk.settings).

Model keys are not here on purpose: providers.yaml names the env var per provider (`key_env`) and
the gateway reads it when it builds that provider, so the key never passes through a settings object
that might be logged.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from mycelium_sdk import ServiceSettings


class GatewaySettings(ServiceSettings):
    config: Path = Field(default=Path("/srv/gateway/providers.yaml"), validation_alias="GATEWAY_CONFIG")
