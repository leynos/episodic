"""Shared cost-accounting domain fixtures and builders."""

import datetime as dt

from episodic.cost import CurrencyCode, PricingSourceKind
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    UsageUnit,
)

V1_RETRIEVED_AT = dt.datetime(2026, 6, 4, 9, tzinfo=dt.UTC)


def v1_pricing_snapshot() -> PricingSnapshot:
    """Build a representative schema-version-1 pricing snapshot.

    Returns
    -------
    PricingSnapshot
        Snapshot pricing ``gpt-4o-mini`` chat completions in USD.

    Examples
    --------
    >>> v1_pricing_snapshot().provider_name
    'openai'
    """
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={
            "input_tokens": MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN),
            "output_tokens": MeteredRate.reduced(60, 1_000_000, UsageUnit.TOKEN),
        },
        source_metadata={"source_url": "https://example.test/pricing"},
        retrieved_at=V1_RETRIEVED_AT,
        effective_from=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
    )
