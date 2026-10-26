"""The web gateway's environment, as one validated model (see mycelium_sdk.settings)."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from mycelium_sdk import ServiceSettings

DEV_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]  # `pnpm dev` in frontend/


class WebSettings(ServiceSettings):
    port: int = Field(default=8080, ge=1, le=65535, validation_alias="WEB_PORT")
    token: str | None = Field(
        default=None,
        validation_alias="WEB_TOKEN",
        description="the one login: the browser presents it as a bearer token; empty leaves the gateway open (LAN only)",
    )
    user_name: str = Field(default="Hansen", min_length=1, max_length=60, validation_alias="WEB_USER_NAME")
    buffer: int = Field(
        default=300,
        ge=10,
        le=5000,
        validation_alias="WEB_EVENT_BUFFER",
        description="bus events kept in memory for a page that just opened",
    )
    rpc_timeout: float = Field(
        default=10.0, gt=0, validation_alias="WEB_RPC_TIMEOUT", description="seconds a /rpc call waits by default"
    )
    # NoDecode: pydantic-settings would otherwise JSON-decode the env value (and refuse "a,b"); the validator splits it
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=DEV_ORIGINS,
        validation_alias="WEB_CORS_ORIGINS",
        description="browser origins the app is served from, comma separated; behind one Caddy host none is needed",
    )

    @field_validator("token", mode="before")
    @classmethod
    def _empty_means_open(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _comma_list(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v
