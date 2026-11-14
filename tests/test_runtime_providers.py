"""Unit tests for the shared default clock and identifier providers."""

import datetime as dt

from episodic.runtime_providers import utc_now, uuid7


def test_utc_now_returns_a_timezone_aware_utc_timestamp() -> None:
    """The default clock stamps records in UTC, never in naive local time."""
    stamp = utc_now()

    assert stamp.tzinfo is dt.UTC, "Expected the default clock to be UTC-aware."


def test_uuid7_returns_time_ordered_version_seven_identifiers() -> None:
    """The default identifier factory yields version 7 UUIDs."""
    first = uuid7()
    second = uuid7()

    assert first.version == 7, "Expected a version 7 UUID."
    assert first != second, "Expected each call to yield a new identifier."
