"""Boundary and property checks for the duplication benchmark."""

import typing as typ

import pytest
from hypothesis import given
from hypothesis import strategies as st

from benchmarks.duplication.corpus.controls import parse_ratio
from benchmarks.duplication.corpus.pricing import recent_error_messages
from benchmarks.duplication.corpus.reporting import latest_alert_titles
from benchmarks.duplication.models import Expectation, Fragment, Lane, PairFinding
from benchmarks.duplication.score import score_findings


@pytest.mark.parametrize("ratio", ["0%", "3:4", "0", "1.0"])
def test_parse_ratio_returns_non_negative_fractions(ratio: str) -> None:
    """Accepted ratio forms resolve to non-negative fractions."""
    assert parse_ratio(ratio) >= 0, f"Expected {ratio!r} to be non-negative."


@pytest.mark.parametrize("ratio", ["-20%", "-1:2", "-0.5"])
def test_parse_ratio_rejects_negative_fractions(ratio: str) -> None:
    """Percentage, colon, and bare forms reject negative fractions."""
    with pytest.raises(ValueError, match="ratio must not be negative"):
        parse_ratio(ratio)


@pytest.mark.parametrize("ratio", ["inf", "-inf"])
def test_parse_ratio_rejects_non_finite_fractions(ratio: str) -> None:
    """Infinite ratio forms cannot enter the labelled benchmark corpus."""
    with pytest.raises(ValueError, match="ratio must be finite"):
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


@given(
    events=st.lists(
        st.fixed_dictionaries({
            "level": st.sampled_from(("error", "info", "warning")),
            "message": st.text(max_size=20),
        }),
        max_size=30,
    ),
    limit=st.integers(min_value=-5, max_value=35),
)
def test_message_collectors_preserve_error_order_and_limit(
    events: list[dict[str, str]],
    limit: int,
) -> None:
    """Aligned collectors return the same bounded ordered error messages."""
    expected = [
        event["message"]
        for event in events
        if event["level"] == "error" and event["message"]
    ][: max(limit, 0)]
    object_events = typ.cast("list[dict[str, object]]", events)
    assert recent_error_messages(object_events, limit) == expected, (
        "Pricing collector must retain the requested ordered error messages."
    )
    assert latest_alert_titles(object_events, limit) == expected, (
        "Reporting collector must retain the requested ordered error messages."
    )


@given(
    first_offset=st.integers(min_value=-5, max_value=5),
    second_offset=st.integers(min_value=-5, max_value=5),
    member_order=st.integers(min_value=0, max_value=1),
    repeat_count=st.integers(min_value=1, max_value=5),
)
def test_score_deduplicates_overlapping_unordered_findings(
    first_offset: int,
    second_offset: int,
    member_order: int,
    repeat_count: int,
) -> None:
    """Scoring credits one overlapping clone regardless of report order."""
    first = Fragment(path="first.py", start_line=20, end_line=40)
    second = Fragment(path="second.py", start_line=20, end_line=40)
    expectation = Expectation(
        identifier="clone",
        lane=Lane.SYNTACTIC_CLONE,
        is_clone=True,
        first=first,
        second=second,
    )
    finding_members = (
        Fragment(
            path="first.py",
            start_line=20 + first_offset,
            end_line=40 + first_offset,
        ),
        Fragment(
            path="second.py",
            start_line=20 + second_offset,
            end_line=40 + second_offset,
        ),
    )
    reported_first, reported_second = (
        reversed(finding_members) if member_order else finding_members
    )
    finding = PairFinding(
        first=reported_first,
        second=reported_second,
        lane=Lane.SYNTACTIC_CLONE,
        category="candidate",
        similarity=1.0,
    )

    score = score_findings([expectation], [finding] * repeat_count)[
        Lane.SYNTACTIC_CLONE
    ]

    assert score.true_positives == 1, "One label must receive one clone credit."
    assert score.false_positives == 0, "A labelled clone must not be a false positive."
    assert score.false_negatives == 0, (
        "A matched clone must not remain a false negative."
    )
    assert score.true_negatives == 0, "The generated input has no non-clone label."
    assert score.unmatched_findings == 0, "Overlapping reports must match the label."
