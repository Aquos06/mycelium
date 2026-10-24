"""A pydantic model as a tool's input_schema, trimmed for a model's eyes.

    input_schema(RememberArgs) -> {"type": "object", "properties": {...}, "required": [...]}

No titles, no defaults, `X | None` shown as plain X (the field is already optional), and nested
models inlined instead of `$ref`s into `$defs`, because not every vendor resolves references in a
tool schema. Main's planner tools and memory's consolidation use the same function, so every
structured output the system asks a model for is described the same way.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

MAX_DEPTH = 20  # a self-referencing model would otherwise inline forever


def input_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    return _trim(_inline(raw, defs, 0))


def _inline(node: Any, defs: dict[str, Any], depth: int) -> Any:
    if depth > MAX_DEPTH:
        return {"type": "object"}
    if isinstance(node, list):
        return [_inline(n, defs, depth) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        target = dict(defs.get(name, {"type": "object"}))
        extra = {k: v for k, v in node.items() if k != "$ref"}  # a description next to the $ref survives
        return _inline({**target, **extra}, defs, depth + 1)
    return {k: _inline(v, defs, depth) for k, v in node.items()}


def _trim(node: Any, properties: bool = False) -> Any:
    """`properties` is True when the dict's keys are field names (a field may be called title or default)."""
    if isinstance(node, list):
        return [_trim(n) for n in node]
    if not isinstance(node, dict):
        return node
    if properties:
        return {k: _trim(v) for k, v in node.items()}
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o != {"type": "null"}]
        if len(options) == 1:  # Optional[X]: just describe X
            node = {k: v for k, v in {**node, **options[0]}.items() if k != "anyOf"}
    return {k: _trim(v, properties=(k == "properties")) for k, v in node.items() if k not in ("title", "default")}
