"""Unit tests for the rubric-score storage contract on QA artefacts.

The score is validated and stored at four decimal places, matching the
``NUMERIC(5, 4)`` column. These cases pin the rounding rule so validation,
persistence, JSON serialization, and reconstruction cannot drift apart.
"""

import decimal

import pytest

from tests.fixtures.qa_artefact_builders import summary

_FOUR_DECIMAL_PLACES = -4


@pytest.mark.parametrize(
    ("rubric_score", "stored"),
    [
        (decimal.Decimal(0), decimal.Decimal("0.0000")),
        (decimal.Decimal(1), decimal.Decimal("1.0000")),
        (decimal.Decimal("0.5"), decimal.Decimal("0.5000")),
        # Rounded half-to-even, exactly as the NUMERIC(5, 4) column stores it.
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
