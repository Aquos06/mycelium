"""A coding agent's task (coders/agent.py): what it reads as /work/PROMPT.md in its container.

The agent works in the module's folder and runs the tests itself, so it is told how to work rather than
given the files. Its CLI takes one message: the coder sends the system and user parts as one text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mycelium_sdk import Prompt

from .brief import coder_test_file, spec_text

if TYPE_CHECKING:
    from ..schemas import CoderContext

FEEDBACK_MAX = 4000  # characters of a failure's output: the tail, where pytest says why
HOW = """\
## How to work

You are in the module's folder. Read CONTRACT.md and SPEC.md, then:

1. Write `manifest.yaml`, `app/main.py` (helpers in `app/` if needed) and `{test_file}`.
2. Run `python -m pytest -q tests` and fix the module until every test passes, tests/test_contract.py included
   (it is the builder's: make the module pass it, do not edit it).
3. Check the manifest: `python -c "from mycelium_sdk import load_manifest; load_manifest('manifest.yaml')"`.

Stop when both pass. Change no other file, install nothing (standard library only), reach no network."""


def agent_prompt(ctx: CoderContext) -> Prompt:
    parts = [spec_text(ctx.name, ctx.spec), HOW.format(test_file=coder_test_file(ctx.name))]
    if ctx.feedback is not None:
        parts.append(
            f"## Round {ctx.round}: the last round failed at {ctx.feedback.stage}\n\n"
            f"```\n{ctx.feedback.output[-FEEDBACK_MAX:]}\n```\n\nThe folder is as that round left it. Fix the cause."
        )
    return Prompt(
        system=f"You are writing one mycelium module, `{ctx.name}`, for a personal assistant that grows its own "
        f"software.\n\n{ctx.brief.text()}",
        user="\n\n".join(parts),
    )
