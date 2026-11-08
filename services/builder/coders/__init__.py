"""The coders a build can use. The default is the one chosen (rpc.build.default), else BUILDER_CODER; a build may
name another.

base.py       Coder, CoderError (this round failed), CoderUnavailable (the build stops); what a coder is
              given and gives back (CoderContext, CoderResult) is in schemas/coder.py
mycelium.py   ours, the default: file by file through the gateway's `coder` slot, whatever model is behind it
agent.py      a coding agent (OpenCode, Claude Code, Codex, Aider) in a container the supervisor runs
"""

from .agent import AgentCoder, AgentRoster
from .base import Coder, CoderError, CoderUnavailable
from .mycelium import MyceliumCoder

__all__ = [
    "AgentCoder",
    "AgentRoster",
    "Coder",
    "CoderError",
    "CoderUnavailable",
    "MyceliumCoder",
]
