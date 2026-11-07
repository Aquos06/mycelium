"""`show`'s side in Main: its arguments, and what a turn gathers for it. The blocks themselves, how they are made
from a module's reply and how they read, are the SDK's (mycelium_sdk.blocks), shared with the module pages.

`show` takes a module's view by name (`spending.week`: Main asks the module for that view's data itself), or a
request the planner called this turn with ask_module and where in its reply the data is. Either way every number
on screen is the module's.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from mycelium_sdk.blocks import Block, BlockSpec, ChartType, FieldArg, Formatter, Kind
from mycelium_sdk.views import View

MAX_BLOCKS = 4  # under one reply


class ShowArgs(BaseModel):
    view: str = Field(
        default="",
        max_length=90,
        description="a view listed under Modules, as `module.view` (spending.week): Main gets its data itself",
    )
    kind: Kind | None = Field(
        default=None,
        description=(
            "without a view: table (a list of entries) · chart (numbers by a name or over time) · stats (a few "
            "headline numbers) · details (one record) · meter (one number against a goal)"
        ),
    )
    source: str = Field(
        default="",
        max_length=90,
        description="without a view: the request you called with ask_module in this turn, as `module.action`: expenses.history",
    )
    path: str = Field(
        default="",
        max_length=120,
        description="where the data is in that reply, as dotted keys: expenses, by_category; empty for the whole reply",
    )
    title: str = Field(default="", max_length=80, description="a short title")
    fields: list[FieldArg] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "table: its columns, in order · chart: the name or date field first, then 1 to 4 number fields · "
            "stats, details: the values to show · meter: the value, then the goal's field if the data has one. "
            "Empty: the data's own fields"
        ),
    )
    chart: ChartType = Field(
        default=ChartType.BAR, description="chart only: bar for amounts by name, line or area for over time"
    )
    goal: float | None = Field(default=None, description="meter only: the goal when the data has none (2000 for 2 l)")

    @model_validator(mode="after")
    def _view_or_data(self) -> ShowArgs:
        if not self.view and (self.kind is None or not self.source):
            raise ValueError(
                "give a `view` listed under Modules, or `kind` and `source` (a request you asked this turn)"
            )
        return self

    def spec(self) -> BlockSpec:
        """How to see the data, as the planner asked (a view brings its own)."""
        return BlockSpec(
            kind=self.kind or Kind.TABLE,
            path=self.path,
            title=self.title,
            fields=self.fields,
            chart=self.chart,
            goal=self.goal,
        )


class TurnData(BaseModel):
    """What this turn has gathered for `show`: each module reply by `module.action` (the latest), the blocks shown
    so far, the views of the running modules, and how values are written."""

    replies: dict[str, dict[str, Any]] = Field(default_factory=dict)
    blocks: list[Block] = Field(default_factory=list)
    views: dict[str, dict[str, View]] = Field(default_factory=dict)  # module -> its views that can be shown
    formatter: Formatter = Field(default_factory=Formatter)
