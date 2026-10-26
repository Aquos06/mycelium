"""The base every payload of this service derives from, and the channel name.

House rule: functions take and return models, never bare dicts. `extra="forbid"` turns a renamed or
mistyped field into a 422 at the door instead of a blank in the app. Dicts survive only where the shape is
not ours: a bus event's `data` and an rpc `payload`, which belong to whichever service answers.

Per-domain models live in `<domain>/schemas.py` (request bodies and replies together).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

CHANNEL = "web"


class WebSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, validate_assignment=True)
