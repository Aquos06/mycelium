"""The one error the job raises."""


class ConsolidationError(ValueError):
    """The model could not be reached, never produced a valid digest, or the vault could not be written.

    A ValueError so the rpc handler turns it into a clean {"ok": false, "error": ...} without a stack trace;
    the run is always traced before it is raised.
    """
