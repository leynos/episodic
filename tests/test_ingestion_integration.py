"""Validation tests for the multi-source ingestion service."""

import typing as typ

import pytest
from _ingestion_service_helpers import _make_raw_source

import tests.test_ingestion_integration_support as ingestion_support
from episodic.canonical.ingestion import MultiSourceRequest

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import SeriesProfile
    from episodic.canonical.ingestion_service import IngestionPipeline


def test_raw_source_helper_rejects_unknown_overrides() -> None:
    """Raw source helper should reject typoed override keys."""
    with pytest.raises(ValueError, match="Invalid override keys"):
        _make_raw_source(**typ.cast("typ.Any", {"unknown": "value"}))


@pytest.fixture
def ingestion_test_context(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
    ingestion_pipeline: IngestionPipeline,
) -> ingestion_support.IngestionTestContext:
    """Compose ingestion test fixtures into a context object."""
    return ingestion_support.IngestionTestContext(
        session_factory=session_factory,
        profile=series_profile_for_ingestion,
        ingestion_pipeline=ingestion_pipeline,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_sources", "series_slug", "expected_error_pattern"),
    [
        (
            [],
            None,
            "At least one raw source",
        ),
        (
            [_make_raw_source()],
            "wrong-slug",
            "Series slug mismatch",
        ),
    ],
    ids=["empty_sources", "slug_mismatch"],
)
async def test_ingest_multi_source_validation_errors(
    ingestion_test_context: ingestion_support.IngestionTestContext,
    raw_sources: list,
    series_slug: str | None,
    expected_error_pattern: str,
) -> None:
    """Multi-source ingestion validates input and raises ValueError."""
    request = MultiSourceRequest(
        raw_sources=raw_sources,
        series_slug=(
            series_slug
            if series_slug is not None
            else ingestion_test_context.profile.slug
        ),
        requested_by="test@example.com",
    )
    await ingestion_support.assert_ingestion_raises(
        ingestion_test_context,
        request,
        expected_error_pattern,
    )
