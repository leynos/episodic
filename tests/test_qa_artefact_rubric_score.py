"""Unit and property tests for the rubric-score precision contract.

The domain holds the score at four decimal places and the column is sized to
match. These cases pin the rounding rule so validation, persistence, JSON
serialization, and reconstruction cannot drift apart.
"""

import decimal

import hypothesis.strategies as st
import pytest
from hypothesis import given

from episodic.canonical.qa_artefact_validation import (
    _RUBRIC_HIGH,
    _RUBRIC_LOW,
    _RUBRIC_TOLERANCE,
    _normalize_rubric_score,
)
from tests.fixtures.qa_artefact_builders import summary

_FOUR_DECIMAL_PLACES = -4


@pytest.mark.parametrize(
    ("rubric_score", "stored"),
    [
        (decimal.Decimal(0), decimal.Decimal("0.0000")),
        (decimal.Decimal(1), decimal.Decimal("1.0000")),
        (decimal.Decimal("0.5"), decimal.Decimal("0.5000")),
        # The domain helper rounds half-to-even. A store that rounds ties away
        # from zero would disagree, so quantizing in the domain is what keeps
        # the stored value independent of the column's own rule.
        (decimal.Decimal("1.00004"), decimal.Decimal("1.0000")),
        (decimal.Decimal("-0.00004"), decimal.Decimal("0.0000")),
        (decimal.Decimal("1.00005"), decimal.Decimal("1.0000")),
        (decimal.Decimal("-0.00005"), decimal.Decimal("0.0000")),
        (decimal.Decimal("0.12345"), decimal.Decimal("0.1234")),
        (decimal.Decimal("0.12355"), decimal.Decimal("0.1236")),
    ],
)
def test_rubric_score_is_stored_at_the_four_decimal_precision(
    rubric_score: decimal.Decimal,
    stored: decimal.Decimal,
) -> None:
    """Construction keeps exactly the value the numeric column would hold."""
    actual = summary(rubric_score=rubric_score).rubric_score

    assert actual == stored, "the score was rounded differently from the column"
    assert actual is not None, "an accepted score must not be dropped"
    assert actual.as_tuple().exponent == _FOUR_DECIMAL_PLACES, (
        "the stored score does not carry four decimal places"
    )


def test_negative_zero_is_normalized_to_an_unsigned_zero() -> None:
    """A negative score that rounds to zero is stored without its sign.

    ``Decimal("-0.0000") == Decimal("0.0000")``, so the equality assertion
    above cannot see the sign; a signed zero would also serialize as
    ``-0.0000`` rather than the ``0.0000`` the column holds.
    """
    stored = summary(rubric_score=decimal.Decimal("-0.00004")).rubric_score

    assert stored is not None, "an accepted score must not be dropped"
    assert not stored.is_signed(), "a rounded zero kept its negative sign"


def test_rubric_score_round_trips_through_its_stored_precision() -> None:
    """Reading a stored score back into the model leaves it unchanged."""
    stored = summary(rubric_score=decimal.Decimal("0.12345")).rubric_score

    assert stored is not None, "an accepted score must not be dropped"
    assert summary(rubric_score=stored).rubric_score == stored, (
        "a score at the storage precision changed when reconstructed"
    )


def test_rubric_score_ignores_the_callers_decimal_context() -> None:
    """A narrow or trap-enabled caller context cannot change the stored value."""
    with decimal.localcontext() as ctx:
        ctx.prec = 4
        ctx.traps[decimal.Inexact] = True

        stored = summary(rubric_score=decimal.Decimal(1)).rubric_score

    assert stored == decimal.Decimal("1.0000"), (
        "the score was quantized under the caller's decimal context"
    )


def test_absent_rubric_score_stays_absent() -> None:
    """An evaluator that reports no score must not acquire one."""
    assert summary(rubric_score=None).rubric_score is None, (
        "an absent score was replaced with a value"
    )


@pytest.mark.parametrize(
    "rubric_score",
    [
        decimal.Decimal("1.00006"),
        decimal.Decimal("-0.00006"),
        decimal.Decimal("NaN"),
        decimal.Decimal("Infinity"),
        decimal.Decimal("-Infinity"),
        decimal.Decimal("1e999"),
    ],
)
def test_rubric_score_rejects_values_the_column_cannot_hold(
    rubric_score: decimal.Decimal,
) -> None:
    """Out-of-range and non-finite scores are rejected, not stored."""
    with pytest.raises(ValueError, match="rubric_score"):
        summary(rubric_score=rubric_score)


# Scores in this window round into the unit interval even when they sit
# slightly outside it, so the normalization property quantifies over the whole
# window rather than the few dozen values a table can enumerate.
_ACCEPTED_SCORES = st.decimals(
    min_value=_RUBRIC_LOW,
    max_value=_RUBRIC_HIGH,
    allow_nan=False,
    allow_infinity=False,
)
# The nearest four-decimal values that cannot round into the interval, so the
# rejection property exercises the boundary rather than far-away magnitudes.
_REJECTED_SCORES = st.one_of(
    st.decimals(
        min_value=decimal.Decimal("1.00006"),
        max_value=decimal.Decimal(2),
        allow_nan=False,
        allow_infinity=False,
    ),
    st.decimals(
        min_value=decimal.Decimal(-1),
        max_value=decimal.Decimal("-0.00006"),
        allow_nan=False,
        allow_infinity=False,
    ),
)


@given(_ACCEPTED_SCORES)
def test_rubric_score_normalization_holds_across_the_rounding_window(
    rubric_score: decimal.Decimal,
) -> None:
    """Every finite score in the window normalizes to a stable unit score."""
    stored = _normalize_rubric_score(rubric_score)

    assert stored is not None, f"{rubric_score} lost an accepted score"
    assert decimal.Decimal(0) <= stored <= decimal.Decimal(1), (
        f"{rubric_score} normalized outside the unit interval: {stored}"
    )
    assert stored.as_tuple().exponent == _FOUR_DECIMAL_PLACES, (
        f"{rubric_score} did not normalize to four decimal places: {stored}"
    )
    assert abs(stored - rubric_score) <= _RUBRIC_TOLERANCE, (
        f"{rubric_score} moved further than one half-quantum: {stored}"
    )
    assert not stored.is_signed(), f"{rubric_score} normalized to a signed zero"
    assert _normalize_rubric_score(stored) == stored, (
        f"{rubric_score} did not survive reconstruction unchanged: {stored}"
    )


@given(_REJECTED_SCORES)
def test_rubric_score_normalization_rejects_scores_outside_the_window(
    rubric_score: decimal.Decimal,
) -> None:
    """A finite score that cannot round into the interval is rejected."""
    with pytest.raises(ValueError, match="rubric_score"):
        _normalize_rubric_score(rubric_score)
