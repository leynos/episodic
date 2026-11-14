"""Default clock and identifier providers shared by service runtimes.

Services take a clock and a UUID factory as injected collaborators so tests can
pin time and identifiers. This module holds the production defaults and their
type aliases once, instead of each runtime declaring its own copy.
"""

import collections.abc as cabc
import datetime as dt
import uuid

type Clock = cabc.Callable[[], dt.datetime]
type UuidFactory = cabc.Callable[[], uuid.UUID]


def utc_now() -> dt.datetime:
    """Return the current timezone-aware UTC timestamp.

    Returns
    -------
    datetime.datetime
        The current time with ``tzinfo`` set to UTC.

    Examples
    --------
    >>> utc_now().tzinfo is dt.UTC
    True
    """
    return dt.datetime.now(dt.UTC)


def uuid7() -> uuid.UUID:
    """Return a time-ordered (version 7) UUID.

    Returns
    -------
    uuid.UUID
        A new version 7 identifier.

    Examples
    --------
    >>> uuid7().version
    7
    """
    return uuid.uuid7()
