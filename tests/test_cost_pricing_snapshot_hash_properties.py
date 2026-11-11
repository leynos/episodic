"""Property tests for pricing snapshot identity."""

import datetime as dt

import hypothesis.strategies as st
from hypothesis import given, settings

from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    UsageUnit,
)
from episodic.cost.pricing_snapshot_hash import (
    canonical_pricing_document,
    pricing_snapshot_content_hash,
)
from episodic.cost.primitives import CurrencyCode, PricingSourceKind
from episodic.json_canonicalization import canonical_json_bytes

_METRICS = ("input_tokens", "output_tokens", "cached_input_tokens")
_AMOUNT = st.integers(min_value=0, max_value=10_000_000)
_RETRIEVED_AT = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)


@st.composite
def _rate_maps(draw: st.DrawFn) -> dict[str, MeteredRate]:
    """Draw a non-empty rate map over a fixed metric set."""
    metrics = draw(st.lists(st.sampled_from(_METRICS), min_size=1, unique=True))
    return {
        metric: MeteredRate.reduced(
            draw(_AMOUNT),
            draw(st.integers(min_value=1, max_value=1_000_000)),
            UsageUnit.TOKEN,
        )
        for metric in metrics
    }


def _snapshot(rates: dict[str, MeteredRate]) -> PricingSnapshot:
    """Build a provider-rate-card snapshot over the drawn rates."""
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates=rates,
        retrieved_at=_RETRIEVED_AT,
    )


@given(rates=_rate_maps())
@settings(max_examples=100)
def test_hash_is_stable_across_reconstruction(
    rates: dict[str, MeteredRate],
) -> None:
    """Equal content always produces the same identity."""
    assert _snapshot(rates).content_hash == _snapshot(dict(rates)).content_hash, (
        "equal content must hash identically"
    )


@given(rates=_rate_maps())
@settings(max_examples=100)
def test_canonical_bytes_ignore_mapping_order(
    rates: dict[str, MeteredRate],
) -> None:
    """Insertion order of rates never leaks into the canonical bytes."""
    reversed_rates = dict(reversed(tuple(rates.items())))
    left = canonical_json_bytes(canonical_pricing_document(_snapshot(rates)))
    right = canonical_json_bytes(canonical_pricing_document(_snapshot(reversed_rates)))

    assert left == right, "canonical bytes must not depend on insertion order"


@given(rates=_rate_maps(), amount=_AMOUNT)
@settings(max_examples=100)
def test_changing_one_rate_changes_the_hash(
    rates: dict[str, MeteredRate],
    amount: int,
) -> None:
    """Any rate change produces a different identity."""
    metric = next(iter(rates))
    current = rates[metric]
    replacement = MeteredRate.reduced(
        amount,
        current.per_units,
        current.unit,
    )
    if replacement == current:
        return
    changed = {**rates, metric: replacement}

    assert _snapshot(changed).content_hash != _snapshot(rates).content_hash, (
        "a changed rate must change the identity"
    )


@given(rates=_rate_maps(), offset_hours=st.integers(min_value=-12, max_value=14))
@settings(max_examples=50)
def test_instant_offset_does_not_change_the_hash(
    rates: dict[str, MeteredRate],
    offset_hours: int,
) -> None:
    """The same instant in another offset is the same identity."""
    timezone = dt.timezone(dt.timedelta(hours=offset_hours))
    shifted = _RETRIEVED_AT.astimezone(timezone)
    base = _snapshot(rates)
    shifted_snapshot = PricingSnapshot(
        service_kind=base.service_kind,
        provider_name=base.provider_name,
        model=base.model,
        operation=base.operation,
        source_kind=base.source_kind,
        currency=base.currency,
        rates=rates,
        retrieved_at=shifted,
    )

    assert pricing_snapshot_content_hash(shifted_snapshot) == base.content_hash, (
        "an equal instant in another offset must hash identically"
    )
