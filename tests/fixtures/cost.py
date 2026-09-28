"""Shared cost-accounting domain fixtures and builders."""

import datetime as dt

from episodic.cost import (
    BillingPeriodKey,
    CurrencyCode,
    PricingSnapshot,
    PricingSnapshotId,
    PricingSourceKind,
)


def pricing_snapshot(snapshot_id: str) -> PricingSnapshot:
    """Build a representative pricing snapshot for persistence tests."""
    return PricingSnapshot(
        pricing_snapshot_id=PricingSnapshotId(snapshot_id),
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        billing_period_key=BillingPeriodKey("2026-06"),
        rates_minor_per_metric={"input_tokens": 100, "output_tokens": 200},
        source_metadata={"source_url": "https://example.test/pricing"},
        content_hash="ensure-hash",
        retrieved_at="2026-06-04T09:00:00Z",
        effective_from=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
    )
