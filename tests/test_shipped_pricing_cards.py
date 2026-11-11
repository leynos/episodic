"""Coverage for the shipped pricing cards."""

import pathlib

import pytest

from episodic.cost.engine import PricingEngine, PricingRequest
from episodic.cost.pricing_catalogue import FilePricingCatalogue
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSubject,
    UsageUnit,
)

_REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CARD_DIRECTORY = _REPOSITORY_ROOT / "config" / "pricing-snapshots"
_CARD = _CARD_DIRECTORY / "openai-2026-05.yaml"
_NOW = "2026-06-04T00:00:00Z"
_SUBJECT = PricingSubject(
    service_kind=PricedService.LLM,
    provider_name="openai",
    model="gpt-4o-mini",
    operation="chat_completions",
)
_USAGE = {"input_tokens": 1_000_000, "cached_input_tokens": 1_000_000}
_CORRECTED_RATE = '    amount_minor: "7.5"\n    per_units: 1000000\n'
_ORIGINAL_RATE = "    amount_minor: 1\n    per_units: 125000\n"


def _catalogue(directory: pathlib.Path) -> FilePricingCatalogue:
    """Load every card in *directory* eagerly."""
    return FilePricingCatalogue.from_directory(directory, now=lambda: _NOW)


@pytest.mark.asyncio
async def test_shipped_catalogue_loads_and_prices_the_corrected_rate() -> None:
    """The shipped cards load and the corrected card prices cached input exactly."""
    snapshot = await _catalogue(_CARD_DIRECTORY).resolve(_SUBJECT)

    assert snapshot.rates["cached_input_tokens"] == MeteredRate.reduced(
        3, 400_000, UsageUnit.TOKEN
    ), "the shipped card must charge 7.5 minor units per million cached tokens"
    cost = PricingEngine.price(
        snapshot,
        PricingRequest(usage=_USAGE, operation="chat_completions"),
    ).computed_cost_minor
    assert cost == 22, f"the corrected card must price the BDD usage at 22, got {cost}"


@pytest.mark.asyncio
async def test_corrected_card_has_a_different_content_hash(
    tmp_path: pathlib.Path,
) -> None:
    """Correcting the cached rate creates a new content-addressed version."""
    text = _CARD.read_text(encoding="utf-8")
    assert _CORRECTED_RATE in text, "the shipped card must carry the corrected rate"
    (tmp_path / _CARD.name).write_text(
        text.replace(_CORRECTED_RATE, _ORIGINAL_RATE, 1),
        encoding="utf-8",
    )

    corrected = await _catalogue(_CARD_DIRECTORY).resolve(_SUBJECT)
    original = await _catalogue(tmp_path).resolve(_SUBJECT)

    assert corrected.content_hash != original.content_hash, (
        "the corrected card must be a new content-addressed version"
    )
