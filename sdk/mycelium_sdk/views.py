"""A module's views: how its data is seen, on its page in the web app and when Main shows it by name.

A manifest may declare them, each a request that only reads, the arguments it takes, and the block it makes
(blocks.py):

    views:
      week:
        title: This week
        request: summary
        args: {from: $week_start}
        show: stats
      by_category: {title: By category, request: summary, args: {from: $month_start}, path: by_category, show: chart}
      entries:
        title: Entries
        request: history
        path: expenses
        show: table
        fields: [day, description, {key: amount, format: money}]

An argument that is a `$` word is a date, worked out when the view is shown: $today, $yesterday, $week_start (the
Monday), $month_start, $year_start, $7_days_ago. A module that declares none is shown from the replies of its
requests that need no argument and only read (`readable`, then blocks.auto). A view is never a request that writes
(add, delete, ...): a page that opens must not change anything.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import Field, field_validator

from .blocks import BlockSpec

if TYPE_CHECKING:
    from .manifest import Manifest

VIEW_ID = re.compile(r"^[a-z][a-z0-9_]{0,40}\Z")
DATE_WORD = re.compile(r"^\$(today|yesterday|week_start|month_start|year_start|(\d{1,3})_days_ago)\Z")
WRITE_VERBS = {
    "add", "log", "record", "save", "store", "set", "update", "put", "track", "delete", "remove", "clear", "reset",
    "drop", "create", "insert", "edit", "undo", "import", "send", "start", "stop", "run", "trigger", "write", "mark",
}  # fmt: skip


def is_write(action: str) -> bool:
    """`add`, `log_water`, `delete-entry`: a request whose name says it changes something."""
    return re.split(r"[-_]", action)[0] in WRITE_VERBS


class View(BlockSpec):
    """One way to see a module's data: a request that only reads, its arguments, and the block it makes."""

    request: str = Field(min_length=1, max_length=40, description="the module's request that has the data")
    args: dict[str, Any] = Field(
        default_factory=dict, description="what to send it; a $ word is a date: $today, $week_start, $7_days_ago"
    )

    @field_validator("args")
    @classmethod
    def _date_words(cls, v: dict[str, Any]) -> dict[str, Any]:
        for name, value in v.items():
            if isinstance(value, str) and value.startswith("$") and not DATE_WORD.match(value):
                raise ValueError(
                    f"{name}: {value!r} is not a date word; one of $today, $yesterday, $week_start, $month_start, "
                    "$year_start, $<n>_days_ago"
                )
        return v


def resolve_args(args: dict[str, Any], today: date) -> dict[str, Any]:
    """The view's arguments for today: each $ word as an ISO date."""
    out = {}
    for name, value in args.items():
        m = DATE_WORD.match(value) if isinstance(value, str) else None
        out[name] = _day(m.group(1), m.group(2), today).isoformat() if m else value
    return out


def _day(word: str, days: str | None, today: date) -> date:
    match word:
        case "today":
            return today
        case "yesterday":
            return today - timedelta(days=1)
        case "week_start":
            return today - timedelta(days=today.weekday())
        case "month_start":
            return today.replace(day=1)
        case "year_start":
            return today.replace(month=1, day=1)
        case _:
            return today - timedelta(days=int(days or 0))


def problem(manifest: Manifest, view_id: str, view: View) -> str | None:
    """Why this view cannot be shown, or None: a request the module does not have, one that writes, an argument
    it does not take, one it needs and is not given, a path its reply does not have."""
    if not VIEW_ID.match(view_id):
        return f"view {view_id!r}: name it in lowercase letters, digits and _"
    if view.request not in manifest.requests:
        return f"view {view_id!r}: no request {view.request!r}; its requests: {', '.join(manifest.requests) or 'none'}"
    if is_write(view.request):
        return f"view {view_id!r}: {view.request!r} changes data; a view only reads (a page that opens changes nothing)"
    spec = manifest.request_specs.get(view.request)
    if spec is None:
        return None
    if unknown := sorted(set(view.args) - set(spec.params)):
        return f"view {view_id!r}: {view.request} takes no {', '.join(unknown)}; it takes {', '.join(spec.params) or 'nothing'}"
    needed = [p for p, t in spec.params.items() if not t.startswith("optional") and p not in view.args]
    if needed:
        return f"view {view_id!r}: {view.request} needs {', '.join(needed)} in `args`"
    root = view.path.split(".")[0]
    if root and spec.returns and root not in spec.returns:
        return f"view {view_id!r}: {view.request} returns no {root!r}; it returns {', '.join(spec.returns)}"
    return None


def problems(manifest: Manifest) -> list[str]:
    """Every declared view that cannot be shown, and why: the builder's check."""
    return [p for vid, v in manifest.views.items() if (p := problem(manifest, vid, v))]


def views_of(manifest: Manifest) -> dict[str, View]:
    """The views a module declares that can be shown, in its order (one that cannot is left out: `problems`)."""
    return {vid: v for vid, v in manifest.views.items() if problem(manifest, vid, v) is None}


def readable(manifest: Manifest) -> list[str]:
    """The requests a page may call on its own: described, needing no argument, and not writing. What a module
    without views shows (blocks.auto, from each one's reply)."""
    out = []
    for action in manifest.requests:
        spec = manifest.request_specs.get(action)
        if spec is None or action == "health" or is_write(action):
            continue
        if all(t.startswith("optional") for t in spec.params.values()):
            out.append(action)
    return out
