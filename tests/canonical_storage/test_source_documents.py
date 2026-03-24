"""Unit tests for canonical storage source document repositories.

Examples
--------
Run the source document repository tests:

>>> pytest tests/canonical_storage/test_source_documents.py
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
from sqlalchemy import exc as sa_exc

from episodic.canonical.domain import (
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
    SourceDocument,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        TeiHeader,
    )


@pytest.mark.asyncio
async def test_source_document_weight_check_constraint(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Weight check constraint rejects values outside [0, 1]."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, job, _ = episode_fixture
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episodes.add(episode)
        await uow.ingestion_jobs.add(job)
        bad_source = SourceDocument(
            id=uuid.uuid4(),
            ingestion_job_id=job.id,
            canonical_episode_id=episode.id,
            reference_document_revision_id=None,
            source_type="web",
            source_uri="https://example.com/invalid",
            weight=1.5,
            content_hash="hash-bad",
            metadata={},
            created_at=now,
        )
        await uow.source_documents.add(bad_source)
        with pytest.raises(
            sa_exc.IntegrityError,
            match=r"ck_source_documents_weight|check|CHECK",
        ):
            await uow.commit()


@pytest.mark.asyncio
async def test_reference_document_revision_id_round_trip(  # noqa: PLR0914 - test requires fixtures for reference doc, revision, series, header, episode, job, source doc, and uow
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Verify that reference_document_revision_id is persisted and loaded correctly."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, job, _ = episode_fixture
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    # Create a reference document and revision to use
    reference_doc = ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=series.id,
        kind=ReferenceDocumentKind.STYLE_GUIDE,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={},
        created_at=now,
        updated_at=now,
        lock_version=1,
    )
    reference_revision = ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=reference_doc.id,
        content={"text": "Test style guide"},
        content_hash="hash-ref-1",
        author="test-author",
        change_note="Initial version",
        created_at=now,
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.reference_documents.add(reference_doc)
        await uow.reference_document_revisions.add(reference_revision)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episodes.add(episode)
        await uow.ingestion_jobs.add(job)
        source_document = SourceDocument(
            id=uuid.uuid4(),
            ingestion_job_id=job.id,
            canonical_episode_id=episode.id,
            reference_document_revision_id=reference_revision.id,
            source_type="web",
            source_uri="https://example.com/test",
            weight=0.5,
            content_hash="hash-test",
            metadata={},
            created_at=now,
        )
        await uow.source_documents.add(source_document)
        await uow.commit()

    # Reload and verify the reference_document_revision_id round-trips correctly
    async with SqlAlchemyUnitOfWork(factory) as uow:
        reloaded = await uow.source_documents.list_for_job(job.id)
        assert len(reloaded) == 1, (
            f"expected one reloaded document, got {len(reloaded)}"
        )
        assert reloaded[0].reference_document_revision_id == reference_revision.id, (
            f"unexpected reference_document_revision_id: "
            f"expected {reference_revision.id}, "
            f"got {reloaded[0].reference_document_revision_id}"
        )
