"""Main's tools: a pydantic model for each tool's arguments, a handler per tool, and a registry that
generates the schema the planner sees and validates every call before it touches the bus.

base.py      Tool, ToolRegistry, ToolContext, ToolSpec, ToolOutcome
memory.py    remember, recall      -> rpc.memory.*
modules.py   ask_module            -> rpc.mod.<module>.<action>
ask.py       ask                   -> ends the turn; Main publishes out.ask
propose.py   propose_module        -> ends the turn; Main stores the proposal, then sends its card
change.py    change_module         -> the same, for a change to a module the builder grew
delete.py    delete_module         -> the same, to delete a module the builder grew (Delete it / Keep it)
lookup.py    what the supervisor and the builder say of one module, for change_module and delete_module
show.py      show                  -> a module's data this turn as a block under the reply (../blocks.py)
remind.py    remind, cancel_reminder -> a reminder kept in Main's KV (../reminders.py), sent by Main's loop

Adding a tool is one argument model, one async handler and one Tool(...) in the registry.
"""

from .ask import ASK, AskArgs
from .base import Tool, ToolContext, ToolOutcome, ToolRegistry, ToolSpec, input_schema, validation_message
from .change import CHANGE_MODULE, ChangeArgs
from .delete import DELETE_MODULE, DeleteArgs
from .memory import RECALL, REMEMBER, NoteType, RecallArgs, RecallPayload, RememberArgs, RememberPayload
from .modules import ASK_MODULE, AskModuleArgs
from .propose import PROPOSE_MODULE, ProposeArgs
from .remind import CANCEL_REMINDER, REMIND, CancelReminderArgs, RemindArgs
from .show import SHOW, ShowArgs

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
    "DeleteArgs",
    "ProposeArgs",
    "RemindArgs",
    "CancelReminderArgs",
    "ShowArgs",
    "NoteType",
    "RecallArgs",
    "RecallPayload",
    "RememberArgs",
    "RememberPayload",
    "default_tools",
]


def default_tools() -> ToolRegistry:
    return ToolRegistry.of(
        REMEMBER, RECALL, ASK_MODULE, SHOW, ASK, PROPOSE_MODULE, CHANGE_MODULE, DELETE_MODULE, REMIND, CANCEL_REMINDER
    )
