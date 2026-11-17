"""Public exception types used by the SDK."""


class AutopsyUsageError(Exception):
    """Raised when SDK instrumentation is used in a structurally invalid way."""


class DataError(Exception):
    """An application error caused by invalid or unusable input data."""


class GateBlocked(Exception):
    """An application-level gate intentionally prevented later work."""
