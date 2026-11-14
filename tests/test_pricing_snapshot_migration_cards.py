"""Fidelity of the shipped 2.4.4 rate cards through the content-address migration.

The fixtures under ``tests/fixtures/legacy_pricing_cards`` are byte copies of
the three cards Episodic 2.4.4 shipped. Each is parsed the way the old loader
parsed it, inserted at the legacy schema, and upgraded in place. The migrated
row must carry the identity the application computes for the same content, so a
change to either canonicalizer is caught by the shipped data rather than by a
synthetic row alone.
"""

import dataclasses as dc
import datetime as dt
import hashlib
import pathlib
import typing as typ
import uuid

import pytest
import yaml

from episodic.cost.pricing_catalogue import FilePricingCatalogue, PricingCatalogueError
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    PricingSubject,
    UsageUnit,
)
from episodic.cost.pricing_snapshot_hash import pricing_snapshot_content_hash
from tests.fixtures.legacy_pricing_snapshots import (
    rows,
    seed_legacy_rows,
    upgrade,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_FIXTURE_DIRECTORY = pathlib.Path(__file__).resolve().parent / "fixtures"
_LEGACY_CARD_DIRECTORY = _FIXTURE_DIRECTORY / "legacy_pricing_cards"
_SHIPPED_CARD_DIRECTORY = (
    pathlib.Path(__file__).resolve().parents[1] / "config" / "pricing-snapshots"
)
_NOW = "2026-09-01T00:00:00Z"

#: Digest of each byte copy, taken from the 2.4.4 release, so a fixture that
#: drifts from the shipped bytes fails instead of quietly weakening the test.
_LEGACY_CARD_DIGESTS = {
    "anthropic-2026-05.yaml": (
        "29aa3e168ec5b996ddeccee3f9f2c4de04badc95514451139384f44e1a3e3920"
    ),
    "openai-2026-05.yaml": (
        "d836c99c41a596e3282d3cac8e96ac16e501d827b84eeced22e906af5fe4f3aa"
    ),
    "openai-2026-08.yaml": (
        "156c9e4673be2a2ab1209dadfe9a618a41afcd20d06713a1d0765e54def80c7b"
    ),
}

#: Subject each shipped card prices, keyed by fixture name.
_SUBJECTS = {
    "anthropic-2026-05.yaml": PricingSubject(
        service_kind=PricedService.LLM,
        provider_name="anthropic",
        model="claude-3-5-haiku-latest",
        operation="messages",
    ),
    "openai-2026-05.yaml": PricingSubject(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
    ),
    "openai-2026-08.yaml": PricingSubject(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-5.6-sol",
        operation="chat_completions",
    ),
}

#: The one card 2.5.1 corrects: its cached-input rate changes from 8 to 7.5
#: minor units per million tokens, so its migrated identity is the old one.
_CORRECTED_CARD = "openai-2026-05.yaml"


def _card_paths() -> list[pathlib.Path]:
    """Return the byte-copy fixtures in a stable order."""
    return sorted(_LEGACY_CARD_DIRECTORY.glob("*.yaml"))


def _parsed_card(path: pathlib.Path) -> dict[str, object]:
    """Parse one legacy card with the schema its loader used."""
    return typ.cast("dict[str, object]", yaml.safe_load(path.read_text("utf-8")))


def _legacy_row(path: pathlib.Path) -> dict[str, object]:
    """Build the legacy database row a 2.4.4 card produced."""
    card = _parsed_card(path)
    return {
        "id": uuid.UUID(str(card["pricing_snapshot_id"])),
        "provider_name": card["provider_name"],
        "model": card["model"],
        "operation": card["operation"],
        "source_kind": card["source_kind"],
        "currency": card["currency"],
        "billing_period_key": card["billing_period_key"],
        "rates_minor_per_metric": card["rates_minor_per_metric"],
        "source_metadata": card["source_metadata"],
        "content_hash": f"legacy-{path.stem}",
        "retrieved_at": dt.datetime.fromisoformat(str(card["retrieved_at"])),
        "effective_from": dt.datetime.fromisoformat(str(card["effective_from"])),
    }


def _without_source_document(snapshot: PricingSnapshot) -> PricingSnapshot:
    """Drop the card text, which the legacy table never stored."""
    return dc.replace(snapshot, source_document=None)


def _legacy_identity(snapshot: PricingSnapshot) -> PricingSnapshot:
    """Restate a corrected card with the rate the legacy table held."""
    corrected = _without_source_document(snapshot)
    return dc.replace(
        corrected,
        rates={
            **corrected.rates,
            "cached_input_tokens": MeteredRate.reduced(8, 1_000_000, UsageUnit.TOKEN),
        },
    )


async def _shipped_snapshot(subject: PricingSubject) -> PricingSnapshot:
    """Resolve the rewritten card the branch ships for *subject*."""
    catalogue = FilePricingCatalogue(_SHIPPED_CARD_DIRECTORY, now=lambda: _NOW)
    return await catalogue.resolve(subject)


def test_legacy_fixtures_are_the_shipped_bytes() -> None:
    """Each fixture is a byte copy of the card 2.4.4 shipped."""
    paths = _card_paths()
    assert {path.name for path in paths} == set(_LEGACY_CARD_DIGESTS), (
        "every shipped 2.4.4 card must have a byte-copy fixture"
    )
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == _LEGACY_CARD_DIGESTS[path.name], (
            f"{path.name} has drifted from the shipped 2.4.4 bytes"
        )


def test_the_current_loader_rejects_the_legacy_cards() -> None:
    """Startup refuses a 2.4.4 card and names the offending file."""
    with pytest.raises(PricingCatalogueError, match="legacy") as rejection:
        FilePricingCatalogue(_LEGACY_CARD_DIRECTORY, now=lambda: _NOW)

    assert ".yaml" in str(rejection.value), (
        "the rejection must name the card that needs converting"
    )


@pytest.mark.asyncio
async def test_migrated_cards_keep_their_shipped_identity(
    migrated_engine: AsyncEngine,
) -> None:
    """Each upgraded card hashes to the identity the application computes."""
    paths = _card_paths()
    by_id = {str(_legacy_row(path)["id"]): path.name for path in paths}

    async with migrated_engine.begin() as connection:
        await seed_legacy_rows(connection, [_legacy_row(path) for path in paths])
        await upgrade(connection)
        converted = {str(row["id"]): row for row in await rows(connection)}

    assert set(converted) == set(by_id), "every shipped card row must survive"

    for identifier, name in by_id.items():
        shipped = await _shipped_snapshot(_SUBJECTS[name])
        expected = _without_source_document(shipped)
        if name == _CORRECTED_CARD:
            expected = _legacy_identity(shipped)
            assert converted[identifier]["content_hash"] != (
                pricing_snapshot_content_hash(_without_source_document(shipped))
            ), "the corrected rate must be a new identity, not the migrated one"

        assert converted[identifier]["content_hash"] == (
            pricing_snapshot_content_hash(expected)
        ), f"the migrated {name} row must keep the identity of its content"
