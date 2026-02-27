"""Unit tests for canonical storage repository list/get behaviour.

Examples
--------
Run the repository behaviour tests:

>>> pytest tests/canonical_storage/test_repositories.py
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import ApprovalEvent, ApprovalState
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


@pytest.mark.asyncio
async def test_repository_getters_and_lists(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Repository getters and list methods return persisted records."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, job, source = episode_fixture
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


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_entity(session_factory: object) -> None:
    """Repository get() returns None for a non-existent identifier."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        result = await uow.series_profiles.get(uuid.uuid4())

    assert result is None, "Expected None when the entity does not exist."
