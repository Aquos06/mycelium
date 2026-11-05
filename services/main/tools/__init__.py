"""Main's tools: a pydantic model for each tool's arguments, a handler per tool, and a registry that
generates the schema the planner sees and validates every call before it touches the bus.

base.py      Tool, ToolRegistry, ToolContext, ToolSpec, ToolOutcome
memory.py    remember, recall      -> rpc.memory.*
modules.py   ask_module            -> rpc.mod.<module>.<action>
ask.py       ask                   -> ends the turn; Main publishes out.ask
propose.py   propose_module        -> ends the turn; Main stores the proposal, then sends its card
change.py    change_module         -> the same, for a change to a module the builder grew

Adding a tool is one argument model, one async handler and one Tool(...) in the registry.
"""

from .ask import ASK, AskArgs
from .base import Tool, ToolContext, ToolOutcome, ToolRegistry, ToolSpec, input_schema, validation_message
from .change import CHANGE_MODULE, ChangeArgs
from .memory import RECALL, REMEMBER, NoteType, RecallArgs, RecallPayload, RememberArgs, RememberPayload
from .modules import ASK_MODULE, AskModuleArgs
from .propose import PROPOSE_MODULE, ProposeArgs

__all__ = [
    "Tool",
    "ToolContext",
    "ToolOutcome",
    "ToolRegistry",
    "ToolSpec",
    "input_schema",
    "validation_message",
    "AskArgs",
    "AskModuleArgs",
    "ChangeArgs",
    "ProposeArgs",
    "NoteType",
    "RecallArgs",
    "RecallPayload",
    "RememberArgs",
    "RememberPayload",
    "default_tools",
]


def default_tools() -> ToolRegistry:
    return ToolRegistry.of(REMEMBER, RECALL, ASK_MODULE, ASK, PROPOSE_MODULE, CHANGE_MODULE)
