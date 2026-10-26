"""Routing only. The version is the installed SDK's: the one number every image carries."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

from ..api.deps import Gateway, Settings
from .schemas import Health

router = APIRouter()


def sdk_version() -> str:
    try:
        return version("mycelium-sdk")
    except PackageNotFoundError:  # a checkout without the SDK installed as a package
        return "0.0.0"


@router.get("/health", response_model=Health, summary="the gateway's state; also the app's login check")
async def health(gw: Gateway, settings: Settings) -> Health:
    return Health(
        name=settings.user_name,
        version=sdk_version(),
        events=len(gw.recent),
        clients=gw.clients,
        auth=settings.token is not None,
    )
