"""Integration tests for the multi-source ingestion service."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest
from _ingestion_service_helpers import (
    _get_job_record_for_episode,
    _make_raw_source,
)

from episodic.canonical.ingestion import MultiSourceRequest
from episodic.canonical.ingestion_service import ingest_multi_source
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import SeriesProfile
    from episodic.canonical.ingestion_service import IngestionPipeline


class SourcePriorityRecord(typ.TypedDict):
    """Serialized source-priority record in TEI provenance metadata."""

    priority: int
    source_uri: str
    source_type: str
    weight: float
    content_hash: str


class TeiHeaderProvenanceRecord(typ.TypedDict):
    """Serialized TEI header provenance metadata payload."""

    capture_context: str
    ingestion_timestamp: str
    source_priorities: list[SourcePriorityRecord]
    reviewer_identities: list[str]


def _require_provenance_payload(
    payload: dict[str, object],
) -> TeiHeaderProvenanceRecord:
    """Return the TEI header provenance payload with runtime checks."""
    provenance = payload.get("episodic_provenance")
    assert isinstance(provenance, dict), (
        "Expected TEI header payload to include dict provenance metadata."
    )
    return typ.cast("TeiHeaderProvenanceRecord", provenance)


def _verify_provenance_metadata(
    provenance: TeiHeaderProvenanceRecord,
    expected_reviewer: str,
    expected_source_uris: list[str],
) -> None:
    """Verify provenance metadata values for an ingested TEI header."""
    timestamp = provenance.get("ingestion_timestamp")
    assert isinstance(timestamp, str), "Expected ingestion timestamp as string."
    assert dt.datetime.fromisoformat(timestamp).tzinfo is not None, (
        "Expected timezone-aware ingestion timestamp."
    )
    assert provenance.get("reviewer_identities") == [expected_reviewer], (
        "Expected reviewer identity to be captured from request actor."
    )
    priorities = provenance["source_priorities"]
    assert len(priorities) == len(expected_source_uris), (
        "Expected one priority entry per source."
    )
    actual_source_uris = [priority["source_uri"] for priority in priorities]
    assert actual_source_uris == expected_source_uris, (
        "Expected source priorities to match source URI order."
    )


def _verify_source_documents(
    documents: list[typ.Any],
    expected_count: int,
) -> None:
    """Verify persisted source document count and weight bounds."""
    assert len(documents) == expected_count, (
        "Expected all input sources to be persisted as source documents."
    )
    for document in documents:
        assert document.weight > 0.0, (
            "Expected persisted source weight to be greater than zero."
        )
        assert document.weight <= 1.0, (
            "Expected persisted source weight to be capped at one."
        )


@pytest.mark.asyncio
async def test_ingest_multi_source_end_to_end(
    session_factory: typ.Callable[[], AsyncSession],
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
    assert header is not None, "Expected a persisted TEI header."

    provenance = _require_provenance_payload(header.payload)
    _verify_provenance_metadata(
        provenance=provenance,
        expected_reviewer="producer@example.com",
        expected_source_uris=[
            "s3://bucket/transcript.txt",
            "s3://bucket/brief.txt",
        ],
    )

    job_record = await _get_job_record_for_episode(session_factory, episode.id)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    _verify_source_documents(documents=documents, expected_count=2)


@pytest.mark.asyncio
async def test_ingest_multi_source_preserves_all_sources(
    session_factory: typ.Callable[[], AsyncSession],
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
    ingestion_pipeline: IngestionPipeline,
) -> None:
    """Submitting zero raw sources raises ValueError."""
    profile = series_profile_for_ingestion

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
                ingestion_pipeline,
            )


@pytest.mark.asyncio
async def test_ingest_multi_source_slug_mismatch_raises(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
    ingestion_pipeline: IngestionPipeline,
) -> None:
    """Mismatched series slug raises ValueError."""
    profile = series_profile_for_ingestion

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
                ingestion_pipeline,
            )


@pytest.mark.asyncio
async def test_ingest_multi_source_records_conflict_metadata(
    session_factory: typ.Callable[[], AsyncSession],
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

    provenance = _require_provenance_payload(header.payload)
    priorities = provenance["source_priorities"]
    assert priorities[0]["source_uri"] == "s3://bucket/winner.txt", (
        "Expected winner source to lead priority ordering."
    )
    assert priorities[1]["source_uri"] == "s3://bucket/loser.txt", (
        "Expected loser source to follow in priority ordering."
    )
