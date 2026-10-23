"""Reading the raw event log, the source of truth, one local day at a time.

base.py       the EventSource protocol, what counts as memory material, local day bounds
jsonl.py      JsonlEvents: a .jsonl file (fixtures, replays)
postgres.py   PostgresEvents: the tracer's `events` table

Requests and traces are not memory material: a request is a question the system asked itself, a
trace is a decision about an event that is already in the log.
"""

from .base import NOT_MATERIAL, EventSource, day_bounds, is_memory_material
from .jsonl import JsonlEvents
from .postgres import PostgresEvents

__all__ = ["NOT_MATERIAL", "EventSource", "JsonlEvents", "PostgresEvents", "day_bounds", "is_memory_material"]
