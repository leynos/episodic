"""End-to-end integration tests for the multi-source ingestion service."""

import typing as typ

import pytest
from _ingestion_service_helpers import _make_raw_source

import tests.test_ingestion_integration_support as ingestion_support
from episodic.canonical.ingestion import MultiSourceRequest
from episodic.canonical.ingestion_service import ingest_multi_source
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.test_uuid_assertions import assert_uuid7

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import SeriesProfile
    from episodic.canonical.ingestion_service import IngestionPipeline


@pytest.mark.asyncio
async def test_ingest_multi_source_end_to_end(
    session_factory: cabc.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
    ingestion_pipeline: IngestionPipeline,
) -> None:
    """End-to-end integration test for multi-source ingestion."""
    profile = series_profile_for_ingestion

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
            ingestion_pipeline,
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        persisted = await uow.episodes.get(episode.id)
        assert persisted is not None, (
            "Expected persisted episode to be retrievable after ingestion."
        )
        header = await uow.tei_headers.get(persisted.tei_header_id)

    assert persisted.title == "Primary Episode", (
        "Expected winning source title to persist as canonical episode title."
    )
    assert_uuid7(persisted.id, "canonical episode")
    assert_uuid7(persisted.tei_header_id, "TEI header reference")
    assert header is not None, "Expected a persisted TEI header."
    assert_uuid7(header.id, "TEI header")

    provenance = ingestion_support.require_provenance_payload(header.payload)
    ingestion_support.verify_provenance_metadata(
        provenance,
        "producer@example.com",
        [
            "s3://bucket/transcript.txt",
            "s3://bucket/brief.txt",
        ],
    )

    job_record = await ingestion_support.get_job_record_for_episode(
        session_factory, episode.id
    )
    assert_uuid7(job_record.id, "ingestion job")

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    ingestion_support.verify_source_documents(documents, expected_count=2)


@pytest.mark.asyncio
async def test_ingest_multi_source_preserves_all_sources(
    session_factory: cabc.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
    ingestion_pipeline: IngestionPipeline,
) -> None:
    """All sources are persisted, even those rejected in conflict resolution."""
    profile = series_profile_for_ingestion

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
            ingestion_pipeline,
        )

    job_record = await ingestion_support.get_job_record_for_episode(
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
async def test_ingest_multi_source_records_conflict_metadata(
    session_factory: cabc.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
    ingestion_pipeline: IngestionPipeline,
) -> None:
    """Conflict-resolution metadata is recorded in source document metadata."""
    profile = series_profile_for_ingestion

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
            ingestion_pipeline,
        )
        persisted = await uow.episodes.get(episode.id)
        assert persisted is not None, "Expected persisted canonical episode."
        header = await uow.tei_headers.get(persisted.tei_header_id)
        assert header is not None, "Expected persisted TEI header."

    job_record = await ingestion_support.get_job_record_for_episode(
        session_factory,
        episode.id,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    for doc in documents:
        assert "conflict_resolution" in doc.metadata, (
            "Expected conflict-resolution metadata to be attached to each source."
        )
        cr = typ.cast("dict[str, object]", doc.metadata["conflict_resolution"])
        assert "preferred_sources" in cr, (
            "Expected conflict metadata to include preferred sources."
        )
        assert "rejected_sources" in cr, (
            "Expected conflict metadata to include rejected sources."
        )
        assert "resolution_notes" in cr, (
            "Expected conflict metadata to include resolver notes."
        )

    provenance = ingestion_support.require_provenance_payload(header.payload)
    priorities = provenance["source_priorities"]
    assert priorities[0]["source_uri"] == "s3://bucket/winner.txt", (
        "Expected winner source to lead priority ordering."
    )
    assert priorities[1]["source_uri"] == "s3://bucket/loser.txt", (
        "Expected loser source to follow in priority ordering."
    )


@pytest.mark.asyncio
async def test_ingest_multi_source_snapshots_resolved_reference_bindings(
    session_factory: cabc.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
    ingestion_pipeline: IngestionPipeline,
) -> None:
    """Series-level resolved bindings should be snapshotted as source documents."""
    profile = series_profile_for_ingestion
    (
        reference_document,
        reference_revision,
        reference_binding,
    ) = await ingestion_support.create_reference_fixtures(session_factory, profile)
    request = ingestion_support.make_reference_ingestion_request(profile)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        episode = await ingest_multi_source(
            uow,
            profile,
            request,
            ingestion_pipeline,
        )

    job_record = await ingestion_support.get_job_record_for_episode(
        session_factory, episode.id
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    ingestion_support.assert_reference_snapshot(
        documents,
        reference_document,
        reference_revision,
        reference_binding,
    )
