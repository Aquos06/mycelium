"""What a module's page shows: each of its views, built from what the module answers now.

The supervisor's registry has the manifest (rpc.sys.list). A module that declares views gets each one: its request
asked with its arguments (dates worked out today), the reply made into the view's block. One that declares none is
shown from the replies of its readable requests (no argument needed, nothing written), each made into blocks by the
reply's own shape. A request is asked once however many views read it; a view that cannot be shown says why, and
the others still show. Nothing here writes: a view of a request that writes is refused before it is asked.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mycelium_sdk import Bus, Manifest
from mycelium_sdk.blocks import BlockError, Formatter, auto, build
from mycelium_sdk.views import is_write, problem, readable, resolve_args

from .schemas import ModuleViews, ViewOut

MAX_AUTO_VIEWS = 8  # blocks for a module without views: a page, not a dump


class NoModule(LookupError):
    pass


async def module_views(bus: Bus, name: str, fmt: Formatter, timeout: float) -> ModuleViews:
    listed = await bus.request("rpc.sys.list", {}, timeout=5.0)
    row = next((r for r in listed.get("modules") or [] if r.get("name") == name), None)
    if row is None:
        raise NoModule(f"no module {name!r}")
    try:
        manifest = Manifest.model_validate({**(row.get("manifest") or {}), "name": name})
    except ValueError as e:
        return ModuleViews(
            name=name,
            running=False,
            declared=False,
            views=[ViewOut(id="manifest", title="Manifest", request="", error=f"its manifest does not read: {e}")],
        )
    running = row.get("status") == "running"
    if not running:
        return ModuleViews(name=name, running=False, declared=bool(manifest.views), views=[])
    asked: dict[str, asyncio.Task[dict[str, Any]]] = {}

    def ask(action: str, args: dict[str, Any]) -> asyncio.Task[dict[str, Any]]:
        key = f"{action} {json.dumps(args, sort_keys=True, default=str)}"
        if key not in asked:
            asked[key] = asyncio.ensure_future(_ask(bus, name, action, args, timeout))
        return asked[key]

    if manifest.views:
        return ModuleViews(name=name, running=True, declared=True, views=await _declared(manifest, fmt, ask))
    return ModuleViews(name=name, running=True, declared=False, views=await _auto(manifest, fmt, ask))


async def _ask(bus: Bus, module: str, action: str, args: dict[str, Any], timeout: float) -> dict[str, Any]:
    if is_write(action):  # never, whatever asked for it
        raise BlockError(f"{action} changes data; a page only reads")
    try:
        reply = await bus.request(f"rpc.mod.{module}.{action}", args, timeout=timeout)
    except Exception as e:  # down, slow: the view says so, the others still show
        raise BlockError(f"{module}.{action} did not answer ({type(e).__name__})") from e
    if reply.get("ok") is False:
        raise BlockError(f"{module}.{action}: {reply.get('error') or 'refused'}")
    return reply


async def _declared(manifest: Manifest, fmt: Formatter, ask: Any) -> list[ViewOut]:
    async def one(vid: str) -> ViewOut:
        view = manifest.views[vid]
        out = ViewOut(id=vid, title=view.title or vid, request=view.request)
        if why := problem(manifest, vid, view):
            return out.model_copy(update={"error": why})
        try:
            reply = await ask(view.request, resolve_args(view.args, fmt.today) if fmt.today else view.args)
            return out.model_copy(update={"block": build(view, reply, fmt, f"{manifest.name}.{view.request}")})
        except BlockError as e:
            return out.model_copy(update={"error": str(e)})

    return list(await asyncio.gather(*(one(vid) for vid in manifest.views)))


async def _auto(manifest: Manifest, fmt: Formatter, ask: Any) -> list[ViewOut]:
    actions = readable(manifest)

    async def one(action: str) -> list[ViewOut]:
        try:
            reply = await ask(action, {})
        except BlockError as e:
            return [ViewOut(id=action, title=action, request=action, error=str(e))]
        blocks = auto(reply, fmt, action)
        return [
            ViewOut(id=f"{action}.{i}", title=b.title or action, request=action, block=b) for i, b in enumerate(blocks)
        ]

    found = await asyncio.gather(*(one(a) for a in actions))
    return [v for vs in found for v in vs][:MAX_AUTO_VIEWS]
