"""Integration tests for the multi-source ingestion service."""

from __future__ import annotations

import typing as typ

import pytest
from _ingestion_service_helpers import (
    _get_job_record_for_episode,
    _make_raw_source,
)

from episodic.canonical.adapters.normaliser import InMemorySourceNormaliser
from episodic.canonical.adapters.resolver import HighestWeightConflictResolver
from episodic.canonical.adapters.weighting import DefaultWeightingStrategy
from episodic.canonical.ingestion import MultiSourceRequest
from episodic.canonical.ingestion_service import IngestionPipeline, ingest_multi_source
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import SeriesProfile


@pytest.mark.asyncio
async def test_ingest_multi_source_end_to_end(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """End-to-end integration test for multi-source ingestion."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    request = MultiSourceRequest(
        raw_sources=[
            _make_raw_source(
                source_type="transcript",
                source_uri="s3://bucket/transcript.txt",
                content="Primary transcript",
                content_hash="hash-primary",
                metadata={"title": "Primary Episode"},
            ),
            _make_raw_source(
                source_type="brief",
                source_uri="s3://bucket/brief.txt",
                content="Background brief",
                content_hash="hash-brief",
                metadata={"title": "Brief Notes"},
            ),
        ],
        series_slug=profile.slug,
        requested_by="producer@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        episode = await ingest_multi_source(
            uow,
            profile,
            request,
            pipeline,
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        persisted = await uow.episodes.get(episode.id)

    assert persisted is not None, (
        "Expected persisted episode to be retrievable after ingestion."
    )
    assert persisted.title == "Primary Episode", (
        "Expected winning source title to persist as canonical episode title."
    )

    job_record = await _get_job_record_for_episode(
        session_factory,
        episode.id,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    assert len(documents) == 2, (
        "Expected all input sources to be persisted as source documents."
    )
    for doc in documents:
        assert doc.weight > 0.0, (
            "Expected persisted source weight to be greater than zero."
        )
        assert doc.weight <= 1.0, (
            "Expected persisted source weight to be capped at one."
        )


@pytest.mark.asyncio
async def test_ingest_multi_source_preserves_all_sources(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """All sources are persisted, even those rejected in conflict resolution."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    source_uris = [
        "s3://bucket/source-1.txt",
        "s3://bucket/source-2.txt",
        "s3://bucket/source-3.txt",
    ]
    request = MultiSourceRequest(
        raw_sources=[
            _make_raw_source(
                source_type="transcript",
                source_uri=source_uris[0],
                content="Source one",
                content_hash="hash-1",
                metadata={"title": "Source One"},
            ),
            _make_raw_source(
                source_type="brief",
                source_uri=source_uris[1],
                content="Source two",
                content_hash="hash-2",
                metadata={"title": "Source Two"},
            ),
            _make_raw_source(
                source_type="rss",
                source_uri=source_uris[2],
                content="Source three",
                content_hash="hash-3",
                metadata={"title": "Source Three"},
            ),
        ],
        series_slug=profile.slug,
        requested_by="test@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        episode = await ingest_multi_source(
            uow,
            profile,
            request,
            pipeline,
        )

    job_record = await _get_job_record_for_episode(
        session_factory,
        episode.id,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    assert len(documents) == 3, "Expected all three sources to be persisted."
    persisted_uris = {doc.source_uri for doc in documents}
    assert persisted_uris == set(source_uris), (
        "Expected persisted source URIs to match all input URIs."
    )


@pytest.mark.asyncio
async def test_ingest_multi_source_empty_sources_raises(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """Submitting zero raw sources raises ValueError."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    request = MultiSourceRequest(
        raw_sources=[],
        series_slug=profile.slug,
        requested_by="test@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ValueError, match="At least one raw source"):
            await ingest_multi_source(
                uow,
                profile,
                request,
                pipeline,
            )


@pytest.mark.asyncio
async def test_ingest_multi_source_slug_mismatch_raises(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """Mismatched series slug raises ValueError."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    request = MultiSourceRequest(
        raw_sources=[_make_raw_source()],
        series_slug="wrong-slug",
        requested_by="test@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ValueError, match="Series slug mismatch"):
            await ingest_multi_source(
                uow,
                profile,
                request,
                pipeline,
            )


@pytest.mark.asyncio
async def test_ingest_multi_source_records_conflict_metadata(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """Conflict-resolution metadata is recorded in source document metadata."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    request = MultiSourceRequest(
        raw_sources=[
            _make_raw_source(
                source_type="transcript",
                source_uri="s3://bucket/winner.txt",
                content="Winner content",
                content_hash="hash-winner",
                metadata={"title": "Winner"},
            ),
            _make_raw_source(
                source_type="rss",
                source_uri="s3://bucket/loser.txt",
                content="Loser content",
                content_hash="hash-loser",
                metadata={"title": "Loser"},
            ),
        ],
        series_slug=profile.slug,
        requested_by="test@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        episode = await ingest_multi_source(
            uow,
            profile,
            request,
            pipeline,
        )

    job_record = await _get_job_record_for_episode(
        session_factory,
        episode.id,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    for doc in documents:
        assert "conflict_resolution" in doc.metadata, (
            "Expected conflict-resolution metadata to be attached to each source."
        )
        cr = doc.metadata["conflict_resolution"]
        assert "preferred_sources" in cr, (
            "Expected conflict metadata to include preferred sources."
        )
        assert "rejected_sources" in cr, (
            "Expected conflict metadata to include rejected sources."
        )
        assert "resolution_notes" in cr, (
            "Expected conflict metadata to include resolver notes."
        )
