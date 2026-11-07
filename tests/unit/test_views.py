"""A module's views (mycelium_sdk.views): declared in its manifest, each a request that only reads, its arguments
(with $ dates) and the block it makes; why one cannot be shown; and what a page may call for a module without any."""

from datetime import date

import pytest

from mycelium_sdk import ManifestError, validate_manifest
from mycelium_sdk.views import is_write, problem, problems, readable, resolve_args, views_of

TUESDAY = date(2026, 11, 3)


def manifest(views=None, **requests):
    return validate_manifest(
        {
            "name": "spending",
            "purpose": "Tracks spending, with totals by category and by day.",
            "requests": requests
            or {
                "add": {
                    "description": "Store one expense.",
                    "params": {"amount": "number"},
                    "returns": {"id": "number"},
                },
                "summary": {
                    "description": "Totals for a date range, all time without dates.",
                    "params": {"from": "optional date", "to": "optional date"},
                    "returns": {"total": "number", "by_category": "map"},
                },
                "history": {
                    "description": "Every expense of one day.",
                    "params": {"day": "date"},
                    "returns": {"expenses": "list"},
                },
            },
            "views": views or {},
        }
    )


WEEK = {"title": "This week", "request": "summary", "args": {"from": "$week_start"}, "show": "stats"}


def test_a_manifest_declares_its_views_in_the_order_it_wants():
    m = manifest({"week": WEEK, "by_category": {"request": "summary", "path": "by_category", "show": "chart"}})
    assert list(views_of(m)) == ["week", "by_category"]
    assert (m.views["week"].kind, m.views["week"].title) == ("stats", "This week")
    assert problems(m) == []


def test_date_words_are_worked_out_when_the_view_is_shown():
    args = {
        "from": "$week_start",
        "to": "$today",
        "since": "$7_days_ago",
        "y": "$year_start",
        "m": "$month_start",
        "n": 3,
    }
    assert resolve_args(args, TUESDAY) == {
        "from": "2026-11-02",  # the Monday
        "to": "2026-11-03",
        "since": "2026-10-27",
        "y": "2026-01-01",
        "m": "2026-11-01",
        "n": 3,
    }
    with pytest.raises(ManifestError, match=r"\$fortnight.*is not a date word"):
        manifest({"week": {**WEEK, "args": {"from": "$fortnight"}}})


@pytest.mark.parametrize(
    "view, said",
    [
        ({"request": "totals", "show": "stats"}, "no request 'totals'; its requests: add, summary, history"),
        ({"request": "add", "show": "stats"}, "'add' changes data; a view only reads"),
        (
            {"request": "summary", "args": {"month": "$today"}, "show": "stats"},
            "summary takes no month; it takes from, to",
        ),
        ({"request": "history", "path": "expenses", "show": "table"}, "history needs day in `args`"),
        (
            {"request": "summary", "path": "by_day", "show": "chart"},
            "summary returns no 'by_day'; it returns total, by_category",
        ),
    ],
)
def test_a_view_that_cannot_be_shown_says_why(view, said):
    m = manifest({"v": view})
    assert said in problem(m, "v", m.views["v"])
    assert problems(m) == [problem(m, "v", m.views["v"])]


def test_a_page_calls_only_requests_that_need_nothing_and_only_read():
    assert readable(manifest()) == ["summary"]  # add writes; history needs a day
    assert [a for a in ("add", "log_water", "delete-entry", "summary", "list", "stats") if is_write(a)] == [
        "add",
        "log_water",
        "delete-entry",
    ]


def test_a_module_without_views_has_none_declared():
    assert views_of(manifest()) == {}
