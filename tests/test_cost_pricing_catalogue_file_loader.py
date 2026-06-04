"""Tests for file-backed pricing catalogue resolution."""

import textwrap
import typing as typ

import pytest

from episodic.cost import BillingPeriodKey, PricingSnapshotId
from episodic.cost.pricing_catalogue import FilePricingCatalogue

if typ.TYPE_CHECKING:
    import pathlib


def _write_snapshot(directory: pathlib.Path, name: str, body: str) -> None:
    """Write a YAML pricing snapshot fixture."""
    (directory / name).write_text(
        textwrap.dedent(body).strip() + "\n", encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_file_pricing_catalogue_resolves_latest_effective_snapshot(
    tmp_path: pathlib.Path,
) -> None:
    """Resolve selects the latest effective matching snapshot."""
    _write_snapshot(
        tmp_path,
        "openai-old.yaml",
        """
        pricing_snapshot_id: 018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f8f
        provider_name: openai
        model: gpt-4o-mini
        operation: chat_completions
        source_kind: provider_rate_card
        currency: USD
        billing_period_key: "2026-06"
        rates_minor_per_metric:
          input_tokens: 100
          output_tokens: 200
        source_metadata:
          source_url: https://example.test/old
        retrieved_at: "2026-05-01T00:00:00Z"
        effective_from: "2026-05-01T00:00:00Z"
        """,
    )
    _write_snapshot(
        tmp_path,
        "openai-new.yaml",
        """
        pricing_snapshot_id: 018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f90
        provider_name: openai
        model: gpt-4o-mini
        operation: chat_completions
        source_kind: provider_rate_card
        currency: USD
        billing_period_key: "2026-06"
        rates_minor_per_metric:
          input_tokens: 150
          output_tokens: 250
        source_metadata:
          source_url: https://example.test/new
        retrieved_at: "2026-05-15T00:00:00Z"
        effective_from: "2026-05-15T00:00:00Z"
        """,
    )
    catalogue = FilePricingCatalogue(tmp_path, now=lambda: "2026-06-04T00:00:00Z")

    snapshot = await catalogue.resolve(
        "openai",
        "gpt-4o-mini",
        "chat_completions",
        BillingPeriodKey("2026-06"),
    )

    assert snapshot.pricing_snapshot_id == PricingSnapshotId(
        "018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f90"
    ), "unexpected pricing_snapshot_id"
    assert snapshot.rates_minor_per_metric["input_tokens"] == 150, (
        "input_tokens rate mismatch"
    )
    assert snapshot.content_hash, "content_hash is missing or empty"


@pytest.mark.asyncio
async def test_file_pricing_catalogue_rejects_missing_snapshot(
    tmp_path: pathlib.Path,
) -> None:
    """Resolve raises LookupError when no snapshot matches."""
    catalogue = FilePricingCatalogue(tmp_path, now=lambda: "2026-06-04T00:00:00Z")

    with pytest.raises(LookupError, match="No pricing snapshot"):
        await catalogue.resolve(
            "openai",
            "gpt-4o-mini",
            "chat_completions",
            BillingPeriodKey("2026-06"),
        )
