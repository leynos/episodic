"""Time parsing helpers for cost accounting."""

import datetime as dt


def parse_instant(value: str, *, error_message: str) -> dt.datetime:
    """Parse an ISO-8601 instant into a timezone-aware datetime.

    Parameters
    ----------
    value : str
        ISO-8601 datetime string to parse.
    error_message : str
        Message to raise when the parsed datetime has no timezone information.

    Returns
    -------
    dt.datetime
        Parsed timezone-aware datetime.

    Raises
    ------
    ValueError
        If the parsed datetime has no ``tzinfo``.

    Examples
    --------
    >>> parse_instant("2026-06-04T10:00:00Z", error_message="Missing timezone")
    datetime.datetime(2026, 6, 4, 10, 0, tzinfo=datetime.timezone.utc)
    """
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(error_message)
    return parsed
