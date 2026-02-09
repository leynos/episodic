"""Unit tests for canonical storage repositories.

Examples
--------
Run the repository test suite:

>>> pytest tests/test_canonical_storage.py
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
from sqlalchemy import exc as sa_exc

from episodic.canonical.domain import (
    ApprovalEvent,
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    IngestionJob,
    IngestionStatus,
    SeriesProfile,
    SourceDocument,
    TeiHeader,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _episode_fixture(
    now: dt.datetime,
) -> tuple[SeriesProfile, TeiHeader, CanonicalEpisode, IngestionJob, SourceDocument]:
    """Return a set of related canonical entities."""
    series_id = uuid.uuid4()
    header_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    job_id = uuid.uuid4()

    series = SeriesProfile(
        id=series_id,
        slug="nightshift",
        title="Nightshift",
        description="After-dark science news.",
        configuration={"tone": "calm"},
        created_at=now,
        updated_at=now,
    )
    header = TeiHeader(
        id=header_id,
        title="Nightshift Episode 1",
        payload={"file_desc": {"title": "Nightshift Episode 1"}},
        raw_xml="<TEI/>",
        created_at=now,
        updated_at=now,
    )
    episode = CanonicalEpisode(
        id=episode_id,
        series_profile_id=series_id,
        tei_header_id=header_id,
        title="Nightshift Episode 1",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    job = IngestionJob(
        id=job_id,
        series_profile_id=series_id,
        target_episode_id=episode_id,
        status=IngestionStatus.COMPLETED,
        requested_at=now,
        started_at=now,
        completed_at=now,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    source = SourceDocument(
        id=uuid.uuid4(),
        ingestion_job_id=job_id,
        canonical_episode_id=episode_id,
        source_type="web",
        source_uri="https://example.com",
        weight=0.75,
        content_hash="hash-1",
        metadata={"kind": "article"},
        created_at=now,
    )

    return (series, header, episode, job, source)


@pytest.mark.asyncio
async def test_series_profile_slug_unique(session_factory: object) -> None:
    """Series profile slugs are unique."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    profile_a = SeriesProfile(
        id=uuid.uuid4(),
        slug="science-hour",
        title="Science Hour",
        description=None,
        configuration={},
        created_at=dt.datetime.now(dt.UTC),
        updated_at=dt.datetime.now(dt.UTC),
    )
    profile_b = SeriesProfile(
        id=uuid.uuid4(),
        slug="science-hour",
        title="Science Hour Replay",
        description=None,
        configuration={},
        created_at=dt.datetime.now(dt.UTC),
        updated_at=dt.datetime.now(dt.UTC),
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(profile_a)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(profile_b)
        with pytest.raises(
            sa_exc.IntegrityError,
            match=r"unique|UNIQUE|duplicate",
        ):
            await uow.commit()


@pytest.mark.asyncio
async def test_can_persist_episode_with_header(session_factory: object) -> None:
    """Episodes persist with linked TEI headers and ingestion metadata."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, job, source = _episode_fixture(now)
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episodes.add(episode)
        await uow.ingestion_jobs.add(job)
        await uow.source_documents.add(source)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.episodes.get(episode.id)

    assert fetched is not None, "Expected the episode to be persisted."
    assert fetched.series_profile_id == series.id, (
        "Expected the episode to reference the series profile."
    )
    assert fetched.tei_header_id == header.id, (
        "Expected the episode to reference the TEI header."
    )


@pytest.mark.asyncio
async def test_repository_getters_and_lists(session_factory: object) -> None:
    """Repository getters and list methods return persisted records."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, job, source = _episode_fixture(now)
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()

        await uow.episodes.add(episode)
        await uow.ingestion_jobs.add(job)
        await uow.source_documents.add(source)
        await uow.flush()
        await uow.approval_events.add(
            ApprovalEvent(
                id=uuid.uuid4(),
                episode_id=episode.id,
                actor="reviewer@example.com",
                from_state=None,
                to_state=ApprovalState.DRAFT,
                note="Initial review.",
                payload={"sources": [source.source_uri]},
                created_at=now,
            )
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        record = await uow.series_profiles.get_by_slug(series.slug)
        assert record is not None, "Expected to fetch the series profile."
        assert record.id == series.id, "Expected the series profile id to match."

        record = await uow.tei_headers.get(header.id)
        assert record is not None, "Expected to fetch the TEI header."
        assert record.id == header.id, "Expected the TEI header id to match."

        record = await uow.ingestion_jobs.get(job.id)
        assert record is not None, "Expected to fetch the ingestion job."
        assert record.id == job.id, "Expected the ingestion job id to match."

        records = await uow.source_documents.list_for_job(job.id)
        assert records, "Expected source documents for the ingestion job."
        assert records[0].ingestion_job_id == job.id, (
            "Expected the document to reference the ingestion job."
        )
        assert records[0].canonical_episode_id == episode.id, (
            "Expected the document to reference the canonical episode."
        )

        records = await uow.approval_events.list_for_episode(episode.id)
        assert records, "Expected approval events for the episode."
        assert records[0].episode_id == episode.id, (
            "Expected the approval event to reference the episode."
        )
