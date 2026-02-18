"""Unit tests for conflict resolution adapters."""

from __future__ import annotations

import pytest
from _ingestion_service_helpers import _make_weighting_result

from episodic.canonical.adapters.resolver import HighestWeightConflictResolver


@pytest.mark.asyncio
async def test_conflict_resolver_selects_highest_weight() -> None:
    """The resolver selects the highest-weighted source as preferred."""
    resolver = HighestWeightConflictResolver()
    high = _make_weighting_result(title="High Priority", weight=0.9)
    low = _make_weighting_result(title="Low Priority", weight=0.3)

    outcome = await resolver.resolve([low, high])

    assert len(outcome.preferred_sources) == 1, "Expected exactly one preferred source."
    assert outcome.preferred_sources[0].source.title == "High Priority", (
        "Expected highest-weight source to be preferred."
    )
    assert len(outcome.rejected_sources) == 1, (
        "Expected non-winning source to be rejected."
    )
    assert outcome.rejected_sources[0].source.title == "Low Priority", (
        "Expected lower-weight source to be rejected."
    )
    assert outcome.merged_title == "High Priority", (
        "Expected merged title to come from the preferred source."
    )


@pytest.mark.asyncio
async def test_conflict_resolver_single_source_no_conflict() -> None:
    """A single source is selected with no rejections."""
    resolver = HighestWeightConflictResolver()
    single = _make_weighting_result(title="Only Source", weight=0.8)

    outcome = await resolver.resolve([single])

    assert len(outcome.preferred_sources) == 1, (
        "Expected single-source input to yield one preferred source."
    )
    assert outcome.preferred_sources[0].source.title == "Only Source", (
        "Expected only source to be selected as preferred."
    )
    assert len(outcome.rejected_sources) == 0, (
        "Expected no rejected sources for single-source input."
    )


@pytest.mark.asyncio
async def test_conflict_resolver_records_resolution_notes() -> None:
    """The resolver produces human-readable resolution notes."""
    resolver = HighestWeightConflictResolver()
    high = _make_weighting_result(title="Winner", weight=0.9)
    low = _make_weighting_result(title="Loser", weight=0.3)

    outcome = await resolver.resolve([high, low])

    assert "Winner" in outcome.resolution_notes, (
        "Expected resolution notes to mention the winning source."
    )
    assert "selected as canonical" in outcome.resolution_notes, (
        "Expected resolution notes to include canonical-selection language."
    )
    assert "Loser" in outcome.resolution_notes, (
        "Expected resolution notes to mention the rejected source."
    )
    assert "rejected" in outcome.resolution_notes, (
        "Expected resolution notes to describe rejection."
    )
