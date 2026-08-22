"""Boundary and property checks for the duplication benchmark."""

import pytest

from benchmarks.duplication.corpus.controls import parse_ratio
from benchmarks.duplication.corpus.pricing import recent_error_messages
from benchmarks.duplication.corpus.reporting import latest_alert_titles


@pytest.mark.parametrize("ratio", ["0%", "3:4", "0", "1.0"])
def test_parse_ratio_returns_non_negative_fractions(ratio: str) -> None:
    """Accepted ratio forms resolve to non-negative fractions."""
    assert parse_ratio(ratio) >= 0, f"Expected {ratio!r} to be non-negative."


@pytest.mark.parametrize("ratio", ["-20%", "-1:2", "-0.5"])
def test_parse_ratio_rejects_negative_fractions(ratio: str) -> None:
    """Percentage, colon, and bare forms reject negative fractions."""
    with pytest.raises(ValueError, match="ratio must not be negative"):
        parse_ratio(ratio)


@pytest.mark.parametrize("limit", [0, -1])
def test_message_collectors_reject_non_positive_limits(limit: int) -> None:
    """Aligned corpus collectors return no messages for non-positive limits."""
    events: list[dict[str, object]] = [{"level": "error", "message": "failed"}]
    assert not recent_error_messages(events, limit), (
        "Pricing collector must reject non-positive limits."
    )
    assert not latest_alert_titles(events, limit), (
        "Reporting collector must reject non-positive limits."
    )
