"""A round in one line, for whoever follows a build: what passed, or what stopped it and the first thing to look at.

tests  "tests failed: 1 failed, 5 passed; test_add_keeps_the_day: KeyError: 'day'"  (pytest -q's own words)
build  "the image did not build: ERROR: No matching distribution found for fastapi==99"
checks "checks: manifest.yaml: request `add` is not described (and 2 more)"
coder  "the coder could not write it: the model did not answer in 120 s"
"""

from __future__ import annotations

import re

from mycelium_sdk.text import one_line

from .schemas import Round, Stage

MAX = 200
COUNTS = re.compile(
    r"(\d+ (?:failed|passed|errors?|skipped|xfailed|xpassed|deselected|warnings?)(?:, \d+ \w+)*) in [\d.]+s"
)
# pytest's short summary: "FAILED tests/test_x.py::test_add[a day] - KeyError: 'day'"; a parametrized id may hold spaces
FIRST_FAILURE = re.compile(r"^(?:FAILED|ERROR) (\S+?(?:\[.*?\])?)(?: - (.+))?$", re.MULTILINE)


def _lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip()]


def pytest_counts(output: str) -> str:
    """pytest's last tally, "1 failed, 5 passed", or ""."""
    found = COUNTS.findall(output)
    return found[-1] if found else ""


def round_summary(rnd: Round) -> str:
    out = rnd.output
    counts = pytest_counts(out)
    if rnd.passed:
        return f"the tests pass ({counts})" if counts else "the tests pass"
    match rnd.stage:
        case Stage.TESTS:
            first = FIRST_FAILURE.search(out)
            where = ""
            if first:
                test = first.group(1).rsplit("::", 1)[-1]
                where = f"; {test}: {first.group(2)}" if first.group(2) else f"; {test}"
            return one_line(f"tests failed: {counts or 'see the output'}{where}", MAX)
        case Stage.BUILD:
            lines = _lines(out)
            errors = [line for line in lines if "error" in line.lower()]
            return one_line(f"the image did not build: {(errors or lines or ['no output'])[-1]}", MAX)
        case Stage.CHECKS:
            lines = _lines(out)
            more = f" (and {len(lines) - 1} more)" if len(lines) > 1 else ""
            return one_line(f"checks: {(lines or ['failed'])[0]}", MAX - len(more)) + more
        case _:
            return one_line(f"the coder could not write it: {(_lines(out) or ['no reason given'])[0]}", MAX)
