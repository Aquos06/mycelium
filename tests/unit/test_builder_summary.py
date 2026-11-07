"""A round in one line: what a build's follower reads in the chat while it runs."""

import pytest

from builder.schemas import Round
from builder.summary import pytest_counts, round_summary

PYTEST_FAIL = """\
.F....                                                                   [100%]
=================================== FAILURES ===================================
____________________________ test_add_keeps_the_day ____________________________
E   KeyError: 'day'
=========================== short test summary info ============================
FAILED tests/test_main.py::test_add_keeps_the_day - KeyError: 'day'
FAILED tests/test_main.py::test_summary_by_day - AssertionError: assert 0 == 85
2 failed, 4 passed in 0.31s
"""


def rnd(stage, output, passed=False):
    return Round(n=1, stage=stage, passed=passed, output=output)


def test_pytest_counts_reads_the_last_tally():
    assert pytest_counts(PYTEST_FAIL) == "2 failed, 4 passed"
    assert pytest_counts("==== 6 passed, 1 warning in 1.02s ====") == "6 passed, 1 warning"
    assert pytest_counts("no tally here") == ""


@pytest.mark.parametrize(
    "round_, line",
    [
        (rnd("tests", "......\n6 passed in 0.20s", passed=True), "the tests pass (6 passed)"),
        (rnd("tests", "", passed=True), "the tests pass"),
        (rnd("tests", PYTEST_FAIL), "tests failed: 2 failed, 4 passed; test_add_keeps_the_day: KeyError: 'day'"),
        (rnd("tests", "ERROR tests/test_main.py\n1 error in 0.10s"), "tests failed: 1 error; tests/test_main.py"),
        (  # a parametrized id with spaces in it: still the first failure, not the next line's
            rnd(
                "tests",
                "FAILED tests/test_main.py::test_add[coffee 85] - KeyError: 'day'\n"
                "FAILED tests/test_main.py::test_sum - AssertionError\n2 failed in 0.2s",
            ),
            "tests failed: 2 failed; test_add[coffee 85]: KeyError: 'day'",
        ),
        (
            rnd("build", "#5 [2/4] RUN pip install\nERROR: No matching distribution found for fastapi==99\nexit 1"),
            "the image did not build: ERROR: No matching distribution found for fastapi==99",
        ),
        (rnd("build", "something went wrong"), "the image did not build: something went wrong"),
        (
            rnd("checks", "manifest.yaml: request `add` is not described\napp/main.py: imports subprocess\nx"),
            "checks: manifest.yaml: request `add` is not described (and 2 more)",
        ),
        (
            rnd("coder", "the model did not answer in 120 s\ntraceback…"),
            "the coder could not write it: the model did not answer in 120 s",
        ),
    ],
)
def test_a_round_in_one_line(round_, line):
    assert round_summary(round_) == line


def test_a_long_line_is_cut():
    line = round_summary(rnd("checks", "x" * 500))
    assert len(line) <= 200 and line.endswith("…")
