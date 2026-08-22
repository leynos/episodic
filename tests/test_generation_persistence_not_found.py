"""Not-found contract tests for draft-generation persistence."""

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.generation_persistence import (
    EpisodeMaterialisationRequest,
    materialise_episode_from_ingestion,
)
from episodic.canonical.source_intake_errors import IngestionJobNotFoundError
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_materialise_episode_from_ingestion_rejects_unknown_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Unknown jobs should retain the source-intake not-found contract."""
    unknown_job_id = uuid.uuid7()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(IngestionJobNotFoundError, match=str(unknown_job_id)):
            await materialise_episode_from_ingestion(
                uow,
                EpisodeMaterialisationRequest(
                    ingestion_job_id=unknown_job_id,
                    title="Unknown job",
                    clock=lambda: dt.datetime(2026, 6, 24, 12, 0, tzinfo=dt.UTC),
                    uuid_factory=uuid.uuid7,
                ),
            )
