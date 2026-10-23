"""One formatter for pydantic errors, shared by every service's rpc handler and Main's tools.

validation_message(e)            -> "messages: List should have at least 1 item; slot: ..."
validation_message(e, "input")   -> the root name used when the error has no field path
"""

from __future__ import annotations

from pydantic import ValidationError


def validation_message(e: ValidationError, root: str = "request") -> str:
    return "; ".join(f"{'.'.join(str(p) for p in err['loc']) or root}: {err['msg']}" for err in e.errors())
