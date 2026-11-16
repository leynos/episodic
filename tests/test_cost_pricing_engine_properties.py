"""Property tests for deterministic cost pricing."""

import datetime as dt
import math
from fractions import Fraction

import hypothesis.strategies as st
import pytest
from hypothesis import event, example, given, settings

from episodic.cost import CurrencyCode, PricingSourceKind
from episodic.cost.engine import PricingEngine, PricingRequest
from episodic.cost.ports import (
    OperationMismatchError,
    PricedCall,
    UnknownPricedMetricError,
)
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    UsageUnit,
)

_METRICS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
)
_OPERATION = "chat_completions"
_LEGACY_PER_UNITS = 1_000_000
_MAX_LEGACY_RATE = 1_000_000
_REDUCIBLE_LEGACY_RATES = (8, 40, 100, 500, 250_000)


def _snapshot(rates: dict[str, MeteredRate]) -> PricingSnapshot:
    """Build a representative pricing snapshot for property tests."""
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="vidai",
        model="mock-gpt",
        operation=_OPERATION,
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates=rates,
        source_metadata={"source": "test"},
        retrieved_at=dt.datetime(2026, 6, 4, tzinfo=dt.UTC),
    )


@st.composite
def _usage_maps(draw: st.DrawFn) -> dict[str, int]:
    """Generate canonical usage maps with at least one priced metric."""
    return draw(
        st.fixed_dictionaries(
            {
                metric: st.integers(min_value=0, max_value=1_000_000)
                for metric in _METRICS
            },
        ),
    )


@st.composite
def _exact_rates(draw: st.DrawFn) -> dict[str, MeteredRate]:
    """Generate whole minor-unit-per-token rates in exact form."""
    amounts = draw(
        st.fixed_dictionaries(
            {metric: st.integers(min_value=0, max_value=20) for metric in _METRICS},
        ),
    )
    return {
        metric: MeteredRate.reduced(amount, 1, UsageUnit.TOKEN)
        for metric, amount in amounts.items()
    }


@st.composite
def _legacy_amounts(draw: st.DrawFn) -> dict[str, int]:
    """Generate legacy integer rates per million, including reducible ones."""
    return draw(
        st.fixed_dictionaries(
            {
                metric: st.one_of(
                    st.sampled_from(_REDUCIBLE_LEGACY_RATES),
                    st.integers(min_value=0, max_value=_MAX_LEGACY_RATE),
                )
                for metric in _METRICS
            },
        ),
    )


def _legacy_rates(amounts: dict[str, int]) -> dict[str, MeteredRate]:
    """Build canonical rates from legacy integer amounts per million."""
    return {
        metric: MeteredRate.reduced(amount, _LEGACY_PER_UNITS, UsageUnit.TOKEN)
        for metric, amount in amounts.items()
    }


def _oracle_cost(amounts: dict[str, int], usage: dict[str, int]) -> int:
    """Legacy oracle: floor each per-metric product, then sum."""
    return sum(
        usage[metric] * amounts[metric] // _LEGACY_PER_UNITS for metric in _METRICS
    )


def _rounded_true_division_cost(amounts: dict[str, int], usage: dict[str, int]) -> int:
    """Seeded fault: sum exact true divisions, then round once at the end."""
    return round(
        sum(
            Fraction(usage[metric] * amounts[metric], _LEGACY_PER_UNITS)
            for metric in _METRICS
        ),
    )


def _add_usage(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    """Add two usage maps metric-wise."""
    return {metric: left[metric] + right[metric] for metric in _METRICS}


def _price(
    engine: PricingEngine,
    snapshot: PricingSnapshot,
    usage: dict[str, int],
) -> PricedCall:
    """Price usage with the module's fixed operation."""
    return engine.price(
        snapshot,
        PricingRequest(usage=usage, operation=_OPERATION),
    )


@given(rates=_exact_rates(), usage_a=_usage_maps(), usage_b=_usage_maps())
@settings(max_examples=100)
def test_pricing_is_additive_for_exact_minor_unit_rates(
    rates: dict[str, MeteredRate],
    usage_a: dict[str, int],
    usage_b: dict[str, int],
) -> None:
    """Pricing usage sums should equal the sum of individually priced usage."""
    engine = PricingEngine()
    snapshot = _snapshot(rates)

    combined = _price(engine, snapshot, _add_usage(usage_a, usage_b))
    left = _price(engine, snapshot, usage_a)
    right = _price(engine, snapshot, usage_b)

    assert combined.computed_cost_minor == (
        left.computed_cost_minor + right.computed_cost_minor
    ), "Expected values to match"


@given(rates=_exact_rates(), usage_a=_usage_maps(), increments=_usage_maps())
@settings(max_examples=100)
def test_pricing_is_monotone_in_each_metric(
    rates: dict[str, MeteredRate],
    usage_a: dict[str, int],
    increments: dict[str, int],
) -> None:
    """Increasing any metric should not reduce computed cost."""
    engine = PricingEngine()
    snapshot = _snapshot(rates)
    usage_b = _add_usage(usage_a, increments)

    assert (
        _price(engine, snapshot, usage_b).computed_cost_minor
        >= _price(
            engine,
            snapshot,
            usage_a,
        ).computed_cost_minor
    ), "Expected values to satisfy the required ordering"


@given(rates=_exact_rates())
@settings(max_examples=50)
def test_zero_usage_produces_zero_cost(rates: dict[str, MeteredRate]) -> None:
    """A call with no usage has no computed cost."""
    priced_call = _price(
        PricingEngine(),
        _snapshot(rates),
        dict.fromkeys(_METRICS, 0),
    )

    assert priced_call.computed_cost_minor == 0, "Expected values to match"


def test_unknown_usage_metric_raises() -> None:
    """Unknown priced metrics must not be silently ignored."""
    snapshot = _snapshot({"input_tokens": MeteredRate.reduced(1, 1, UsageUnit.TOKEN)})

    with pytest.raises(UnknownPricedMetricError, match="unpriced metrics"):
        PricingEngine().price(
            snapshot,
            PricingRequest(
                usage={"input_tokens": 1, "output_tokens": 1},
                operation=_OPERATION,
            ),
        )


def test_operation_mismatch_raises() -> None:
    """Snapshots are bound to their provider operation."""
    snapshot = _snapshot({"input_tokens": MeteredRate.reduced(1, 1, UsageUnit.TOKEN)})

    with pytest.raises(OperationMismatchError, match="operation"):
        PricingEngine().price(
            snapshot,
            PricingRequest(usage={"input_tokens": 1}, operation="responses"),
        )


def test_invalid_currency_code_raises() -> None:
    """Pricing snapshots validate ISO-style currency codes at construction."""
    with pytest.raises(ValueError, match="currency"):
        PricingSnapshot(
            service_kind=PricedService.LLM,
            provider_name="vidai",
            model="mock-gpt",
            operation=_OPERATION,
            source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
            currency=CurrencyCode("usd"),
            rates={"input_tokens": MeteredRate.reduced(1, 1, UsageUnit.TOKEN)},
            source_metadata={"source": "test"},
            retrieved_at=dt.datetime(2026, 6, 4, tzinfo=dt.UTC),
        )


@example(
    amounts=dict.fromkeys(_METRICS, 8),
    usage=dict.fromkeys(_METRICS, 0),
)
@example(
    amounts=dict.fromkeys(_METRICS, 3),
    usage=dict.fromkeys(_METRICS, _LEGACY_PER_UNITS),
)
@given(amounts=_legacy_amounts(), usage=_usage_maps())
@settings(max_examples=100)
def test_legacy_integer_rates_match_floor_division_oracle(
    amounts: dict[str, int],
    usage: dict[str, int],
) -> None:
    """Legacy per-million rates price each metric as ``usage * rate // million``."""
    engine = PricingEngine()
    snapshot = _snapshot(_legacy_rates(amounts))

    for metric in _METRICS:
        event(f"reducible={math.gcd(amounts[metric], _LEGACY_PER_UNITS) > 1}")
        contribution = _price(engine, snapshot, {metric: usage[metric]})
        assert contribution.computed_cost_minor == (
            usage[metric] * amounts[metric] // _LEGACY_PER_UNITS
        ), "Expected the engine to match the legacy per-metric oracle"

    assert _price(engine, snapshot, usage).computed_cost_minor == _oracle_cost(
        amounts, usage
    ), "Expected the engine total to match the legacy oracle"


@given(
    amount=st.integers(min_value=0, max_value=1_000),
    per_units=st.integers(min_value=1, max_value=_LEGACY_PER_UNITS),
    multiplier=st.integers(min_value=1, max_value=8),
    usage=_usage_maps(),
)
@settings(max_examples=100)
def test_reduced_and_unreduced_rate_forms_price_identically(
    amount: int,
    per_units: int,
    multiplier: int,
    usage: dict[str, int],
) -> None:
    """An equal-but-unreduced rate must price exactly like its reduced form."""
    reduced = MeteredRate.reduced(amount, per_units, UsageUnit.TOKEN)
    unreduced = MeteredRate.reduced(
        amount * multiplier,
        per_units * multiplier,
        UsageUnit.TOKEN,
    )

    assert reduced == unreduced, "Expected equal rates to share one canonical form"
    engine = PricingEngine()
    reduced_cost = _price(
        engine,
        _snapshot(dict.fromkeys(_METRICS, reduced)),
        usage,
    ).computed_cost_minor
    unreduced_cost = _price(
        engine,
        _snapshot(dict.fromkeys(_METRICS, unreduced)),
        usage,
    ).computed_cost_minor
    assert reduced_cost == unreduced_cost, "Expected both rate forms to price alike"


def test_eight_per_million_rate_reduces_and_prices_identically() -> None:
    """The fixed 8 -> 1/125000 example shows reducible rates are exercised."""
    assert math.gcd(8, _LEGACY_PER_UNITS) > 1, "Expected a reducible legacy rate"
    reduced = MeteredRate.reduced(8, _LEGACY_PER_UNITS, UsageUnit.TOKEN)
    unreduced = MeteredRate.reduced(
        8 * 125,
        _LEGACY_PER_UNITS * 125,
        UsageUnit.TOKEN,
    )

    assert (reduced.amount_minor, reduced.per_units) == (1, 125_000), (
        "the 8/1_000_000 cent rate must reduce to the exact fraction 1/125_000"
    )
    assert unreduced == reduced, "Expected equal rates to share one canonical form"
    engine = PricingEngine()
    usage = {"input_tokens": 123_456}
    assert (
        _price(
            engine,
            _snapshot({"input_tokens": reduced}),
            usage,
        ).computed_cost_minor
        == _price(
            engine,
            _snapshot({"input_tokens": unreduced}),
            usage,
        ).computed_cost_minor
    ), "Expected both rate forms to price alike"


@example(
    amounts=dict.fromkeys(_METRICS, 1),
    usage=dict.fromkeys(_METRICS, 500_000),
)
@given(amounts=_legacy_amounts(), usage=_usage_maps())
@settings(max_examples=100)
def test_rounded_true_division_fault_is_rejected_by_the_oracle(
    amounts: dict[str, int],
    usage: dict[str, int],
) -> None:
    """Rounding true divisions once at the end must not match the oracle."""
    oracle = _oracle_cost(amounts, usage)
    assert (
        _price(
            PricingEngine(), _snapshot(_legacy_rates(amounts)), usage
        ).computed_cost_minor
        == oracle
    ), "Expected the engine to match the legacy oracle"

    fault = _rounded_true_division_cost(amounts, usage)
    if fault != oracle:
        event("seeded fault disagrees with the oracle")


def test_legacy_rate_witnesses_cover_both_reduction_classes() -> None:
    """Deterministic witnesses keep both reduction classes exercised."""
    reducible = _legacy_rates(dict.fromkeys(_METRICS, 8))["input_tokens"]
    already_reduced = _legacy_rates(dict.fromkeys(_METRICS, 3))["input_tokens"]

    assert reducible.per_units < _LEGACY_PER_UNITS, (
        f"an 8 per million rate must reduce, got {reducible!r}"
    )
    assert already_reduced.per_units == _LEGACY_PER_UNITS, (
        f"a 3 per million rate is already in lowest terms, got {already_reduced!r}"
    )


def test_seeded_rounding_fault_disagrees_with_the_oracle_on_a_witness() -> None:
    """One witness shows the seeded fault is distinguishable from the oracle."""
    amounts = dict.fromkeys(_METRICS, 1)
    usage = dict.fromkeys(_METRICS, 500_000)

    assert _rounded_true_division_cost(amounts, usage) != _oracle_cost(
        amounts, usage
    ), "the seeded true-division fault must disagree with the oracle somewhere"
