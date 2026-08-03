"""Unit tests for conflict resolution adapters."""

import typing as typ

import pytest
from _ingestion_service_helpers import _make_weighting_result

from episodic.canonical.adapters.resolver import HighestWeightConflictResolver

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


@pytest.fixture
def resolver() -> HighestWeightConflictResolver:
    """Provide a conflict resolver instance for adapter tests."""
    return HighestWeightConflictResolver()


@pytest.mark.asyncio
async def test_conflict_resolver_selects_highest_weight(
    resolver: HighestWeightConflictResolver,
) -> None:
    """The resolver selects the highest-weighted source as preferred."""
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
async def test_conflict_resolver_single_source_no_conflict(
    resolver: HighestWeightConflictResolver,
) -> None:
    """A single source is selected with no rejections."""
    single = _make_weighting_result(title="Only Source", weight=0.8)

    outcome = await resolver.resolve([single])

    assert len(outcome.preferred_sources) == 1, (
        "Expected single-source input to yield one preferred source."
    )
    assert outcome.preferred_sources[0].source.title == "Only Source", (
        "Expected only source to be selected as preferred."
    )
    assert outcome.rejected_sources == [], (  # pylint: disable=use-implicit-booleaness-not-comparison  # The explicit empty-list comparison documents the expected collection value.
        "Expected no rejected sources for single-source input."
    )


@pytest.mark.asyncio
async def test_conflict_resolver_records_resolution_notes(
    resolver: HighestWeightConflictResolver,
    snapshot: SnapshotAssertion,
) -> None:
    """The resolver produces human-readable resolution notes."""
    high = _make_weighting_result(title="Winner", weight=0.9)
    low = _make_weighting_result(title="Loser", weight=0.3)

    outcome = await resolver.resolve([high, low])

    assert outcome.resolution_notes == snapshot, "actual output must match snapshot"
