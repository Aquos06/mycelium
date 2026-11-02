"""What the coders read. The wording lives here, never inside a coder: a coder only sends what these build.

brief.py      what every coder is told, whichever it is: Brief (CONTRACT.md, the SDK in a page, hello as the
              example), the spec, the files
mycelium.py   our coder's prompts, one per stage: manifest, code, tests, and fix in later rounds
agent.py      a coding agent's task: the PROMPT.md it reads in its container

Each builds a Prompt (the SDK's: system and user). The system part is who the coder is and the brief, the same
for every call of a build, so a local model's prefix cache keeps it; the user part is the spec and the step.
"""

from .brief import Brief, coder_test_file, files_text, spec_text

__all__ = ["Brief", "coder_test_file", "files_text", "spec_text"]
