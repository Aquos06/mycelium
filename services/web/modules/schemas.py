"""A module's page: its views, each with its block built from the module's own reply (mycelium_sdk.views)."""

from __future__ import annotations

from mycelium_sdk.blocks import Block

from ..schemas import WebSchema


class ViewOut(WebSchema):
    id: str  # the view's name; for a module without views, `<request>.<n>`
    title: str
    request: str  # the module's request it read
    block: Block | None = None  # what it shows; None when it could not be shown (`error`)
    error: str | None = None  # why not: the request refused, timed out, or its reply does not fit the view


class ModuleViews(WebSchema):
    name: str
    running: bool  # a module that is not running shows nothing: there is no one to ask
    declared: bool  # the module declares its views; else they are made from the replies of its readable requests
    views: list[ViewOut]
