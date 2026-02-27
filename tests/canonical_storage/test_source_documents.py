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

from episodic.canonical.domain import SourceDocument
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
