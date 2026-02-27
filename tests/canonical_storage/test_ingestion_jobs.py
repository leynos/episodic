"""Unit tests for canonical storage ingestion job repositories.

Examples
--------
Run the ingestion job repository tests:

>>> pytest tests/canonical_storage/test_ingestion_jobs.py
"""

from __future__ import annotations

import typing as typ

import pytest

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
async def test_ingestion_job_round_trip(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Ingestion job round-trips through add and get."""
    series, header, episode, job, _ = episode_fixture
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episodes.add(episode)
        await uow.ingestion_jobs.add(job)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.ingestion_jobs.get(job.id)

    assert fetched is not None, "Expected the ingestion job to persist."
    assert fetched.id == job.id, "Expected the job id to match."
    assert fetched.status == job.status, "Expected the job status to match."
