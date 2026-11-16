"""Property tests for exact metered rates."""

import math

import hypothesis.strategies as st
from hypothesis import given, settings

from episodic.cost.pricing_snapshot import MeteredRate, UsageUnit

_AMOUNTS = st.integers(min_value=0, max_value=2**53 - 1)
_DENOMINATORS = st.integers(min_value=1, max_value=2**53 - 1)


@st.composite
def _rates(draw: st.DrawFn) -> MeteredRate:
    """Draw a normalized rate from arbitrary non-negative integers."""
    return MeteredRate.reduced(
        draw(_AMOUNTS),
        draw(_DENOMINATORS),
        UsageUnit.TOKEN,
    )


@given(rate=_rates())
@settings(max_examples=200)
def test_reduced_rates_are_in_lowest_terms(rate: MeteredRate) -> None:
    """No common divisor survives normalization."""
    assert math.gcd(rate.amount_minor, rate.per_units) == 1, (
        f"rate {rate.amount_minor}/{rate.per_units} is not in lowest terms"
    )


@given(
    amount=_AMOUNTS,
    per_units=_DENOMINATORS,
)
@settings(max_examples=200)
def test_reduction_preserves_the_ratio(amount: int, per_units: int) -> None:
    """Normalization changes representation, never value."""
    rate = MeteredRate.reduced(amount, per_units, UsageUnit.TOKEN)

    assert rate.amount_minor * per_units == amount * rate.per_units, (
        f"{amount}/{per_units} became {rate.amount_minor}/{rate.per_units}"
    )


@given(rate=_rates())
@settings(max_examples=100)
def test_reduction_is_idempotent(rate: MeteredRate) -> None:
    """Re-normalizing a canonical rate returns an equal rate."""
    assert MeteredRate.reduced(rate.amount_minor, rate.per_units, rate.unit) == rate, (
        f"rate {rate!r} changed under a second reduction"
    )


@given(per_units=_DENOMINATORS)
@settings(max_examples=200)
def test_zero_amount_normalizes_to_one_unit(per_units: int) -> None:
    """A free rate always has the same canonical form."""
    rate = MeteredRate.reduced(0, per_units, UsageUnit.CHARACTER)

    assert (rate.amount_minor, rate.per_units) == (0, 1), (
        f"zero rate over {per_units} units normalized to {rate!r}"
    )
