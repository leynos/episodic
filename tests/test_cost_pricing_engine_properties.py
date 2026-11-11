"""Property tests for deterministic cost pricing."""

import datetime as dt

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

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
