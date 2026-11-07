"""Routing only: WebGateway.views asks the module and builds what its page shows."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from mycelium_sdk.manifest import NAME_RE

from ..api.deps import Gateway
from .schemas import ModuleViews
from .views import NoModule

router = APIRouter()


@router.get(
    "/{name}/views",
    response_model=ModuleViews,
    summary="a module's views, each with its block from what the module answers now (or why it cannot be shown)",
)
async def views(name: str, gw: Gateway) -> ModuleViews:
    if not NAME_RE.match(name):
        raise HTTPException(400, f"not a module name: {name!r}")
    try:
        return await gw.views(name)
    except NoModule as e:
        raise HTTPException(404, str(e)) from None
    except TimeoutError:
        raise HTTPException(504, "the supervisor did not answer: no module list") from None
