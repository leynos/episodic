"""Pricing from exact integer-fraction rates."""

import datetime as dt

import pytest

from episodic.cost.engine import PricingEngine, PricingRequest
from episodic.cost.ports import (
    CurrencyCode,
    OperationMismatchError,
    PricingSourceKind,
    UnknownPricedMetricError,
)
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    UsageUnit,
)

_OPERATION = "chat_completions"


def _snapshot(**rates: MeteredRate) -> PricingSnapshot:
    """Build a rate-card snapshot over the supplied metric rates."""
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation=_OPERATION,
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates=rates,
        retrieved_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
    )


def _price(snapshot: PricingSnapshot, usage: dict[str, int]) -> int:
    """Price usage through the engine and return the cost in minor units."""
    return (
        PricingEngine()
        .price(
            snapshot,
            PricingRequest(usage=usage, operation=_OPERATION),
        )
        .computed_cost_minor
    )


def test_engine_prices_with_the_rate_denominator() -> None:
    """Cost is usage times the rate fraction, not a fixed global scale."""
    snapshot = _snapshot(
        input_tokens=MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN)
    )

    assert _price(snapshot, {"input_tokens": 1_000_000}) == 15, (
        "a 15-per-million rate must charge 15 minor units per million tokens"
    )


def test_engine_truncates_each_metric_independently() -> None:
    """Per-metric integer division is the recorded cost policy."""
    snapshot = _snapshot(
        input_tokens=MeteredRate.reduced(3, 400_000, UsageUnit.TOKEN),
        output_tokens=MeteredRate.reduced(60, 1_000_000, UsageUnit.TOKEN),
    )

    assert (
        _price(
            snapshot,
            {"input_tokens": 1_000_000, "output_tokens": 500_000},
        )
        == 37
    ), "each metric must truncate on its own denominator"


def test_engine_prices_non_token_units() -> None:
    """Rates carry their unit, so characters and milliseconds price alike."""
    snapshot = PricingSnapshot(
        service_kind=PricedService.TTS,
        provider_name="tts-vendor",
        model="voice-v1",
        operation="synthesize",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={"characters": MeteredRate.reduced(5, 60_000, UsageUnit.MILLISECOND)},
        retrieved_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
    )
    priced = PricingEngine().price(
        snapshot,
        PricingRequest(usage={"characters": 60_000}, operation="synthesize"),
    )

    assert priced.computed_cost_minor == 5, (
        "a 5-per-60_000 millisecond rate must charge 5 minor units"
    )
    assert priced.currency == CurrencyCode("USD"), (
        "the priced call must carry the snapshot currency"
    )
    assert priced.is_estimated is False, "an observed usage count is not an estimate"


def test_engine_marks_estimated_calls() -> None:
    """Estimation status passes through to the priced call."""
    snapshot = _snapshot(input_tokens=MeteredRate.reduced(1, 1, UsageUnit.TOKEN))
    priced = PricingEngine().price(
        snapshot,
        PricingRequest(
            usage={"input_tokens": 2}, operation=_OPERATION, is_estimated=True
        ),
    )

    assert priced.is_estimated is True, "the estimate flag must pass through"
    assert priced.computed_cost_minor == 2, (
        "two units at one minor unit each must cost two"
    )


def test_engine_rejects_a_usage_metric_the_snapshot_does_not_price() -> None:
    """Unpriced usage is a defect, never silently free."""
    snapshot = _snapshot(input_tokens=MeteredRate.reduced(1, 1, UsageUnit.TOKEN))

    with pytest.raises(UnknownPricedMetricError, match="output_tokens"):
        _price(snapshot, {"input_tokens": 1, "output_tokens": 1})


def test_engine_rejects_a_mismatched_operation() -> None:
    """A snapshot prices exactly one operation."""
    snapshot = _snapshot(input_tokens=MeteredRate.reduced(1, 1, UsageUnit.TOKEN))

    with pytest.raises(OperationMismatchError, match="operation"):
        PricingEngine().price(
            snapshot,
            PricingRequest(usage={"input_tokens": 1}, operation="responses"),
        )


def test_pricing_request_has_no_billing_period() -> None:
    """Billing periods left the snapshot and the request."""
    request = PricingRequest(usage={"input_tokens": 1}, operation=_OPERATION)

    assert not hasattr(request, "billing_period_key"), (
        "the pricing request must not carry a billing period"
    )
