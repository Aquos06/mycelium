"""Our coder's prompts (coders/mycelium.py), one per stage, each for one forced tool call:

    first round   manifest_prompt -> code_prompt -> tests_prompt
    later rounds  fix_prompt: the files as they are on disk, what failed and its output

Every one is built from disk and the last failure only, so it stays the same size however many rounds a
build takes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mycelium_sdk import Prompt

from ..schemas import Stage
from .brief import coder_test_file, files_text, spec_text

if TYPE_CHECKING:
    from ..schemas import CoderContext

FEEDBACK_MAX = 3000  # characters of a failure's output in the next prompt: the tail, where pytest says why


def system(ctx: CoderContext) -> str:
    return (
        f"You are the coder of mycelium, a personal assistant that grows its own software. You are writing "
        f"one module, `{ctx.name}`, through the tool you are given: call it once, with complete files.\n\n"
        f"{ctx.brief.text()}"
    )


def manifest_prompt(ctx: CoderContext) -> Prompt:
    return Prompt(
        system=system(ctx),
        user=f"{_spec(ctx)}\n\n## Step 1 of 3: the manifest\n\nFrom the spec, decide what `{ctx.name}` listens to, "
        "what it emits and what it answers. Call write_manifest.",
    )


def code_prompt(ctx: CoderContext, files: dict[str, str]) -> Prompt:
    """`files`: the manifest the first step wrote."""
    return Prompt(
        system=system(ctx),
        user=f"{_spec(ctx)}\n\n{files_text(files)}\n\n## Step 2 of 3: the code\n\n"
        "Write app/main.py (and helpers in app/ if it needs them): everything the spec asks, nothing the "
        "manifest does not declare. Call write_files with whole files.",
    )


def tests_prompt(ctx: CoderContext, files: dict[str, str]) -> Prompt:
    """`files`: the manifest and the code."""
    return Prompt(
        system=system(ctx),
        user=f"{_spec(ctx)}\n\n{files_text(files)}\n\n## Step 3 of 3: the tests\n\n"
        f"Write {coder_test_file(ctx.name)}: every request (a good input and a bad one), every subscription (a "
        "message that matters and one that does not), every emit, and anything that depends on the day with "
        'tz="Asia/Taipei". Call write_files.',
    )


def fix_prompt(ctx: CoderContext, files: dict[str, str]) -> Prompt:
    """`files`: the whole folder as the last round left it."""
    fb = ctx.feedback
    assert fb is not None, "a fix round follows a failed one"
    failed = f"## Round {ctx.round}: the last round failed at {fb.stage}\n\n```\n{fb.output[-FEEDBACK_MAX:]}\n```"
    if fb.stage == Stage.CODER:
        failed += "\n\nThe files below may be incomplete: write every file the module needs."
    return Prompt(
        system=system(ctx),
        user=f"{spec_text(ctx.name, ctx.spec)}\n\n## The files now\n\n{files_text(files)}\n\n{failed}\n\n"
        "Fix the cause. Rewrite only the files that need it, each one whole. When a test expects something the "
        "spec does not ask for, fix the test; otherwise fix the code. tests/test_contract.py is the builder's: "
        "make the module pass it, do not write it. Call write_files with a note on what you changed.",
    )


def retry_text(error: str, tool: str) -> str:
    """The follow-up to a reply that did not call the tool."""
    return f"{error}. Call {tool} now, with shorter files if you must."


def _spec(ctx: CoderContext) -> str:
    """The spec; on a first round after one that could not write its files, also how that went wrong."""
    text = spec_text(ctx.name, ctx.spec)
    if ctx.feedback is not None:
        text += (
            f"\n\n## Round {ctx.round}: the last round did not finish writing\n\n{ctx.feedback.output[-FEEDBACK_MAX:]}"
            "\n\nKeep each file short enough to write in one go."
        )
    return text
