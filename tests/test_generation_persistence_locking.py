"""Concurrency-boundary tests for generation materialization."""

import typing as typ

import pytest

from episodic.canonical.generation_persistence import (
    EpisodeMaterialisationRequest,
    materialise_episode_from_ingestion,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.test_generation_persistence import (
    SequentialUuids,
    _clock,
    _persist_ready_job,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import IngestionJob
    from episodic.canonical.ingestion_sources import IngestionJobSource


@pytest.mark.asyncio
async def test_materialisation_releases_job_lock_before_source_work(
    session_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source paging finishes before the materializer locks the job row."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    _, job = await _persist_ready_job(factory)
    source_page_loaded = False

    async with SqlAlchemyUnitOfWork(factory) as uow:
        original_list = uow.ingestion_job_sources.list_for_job_paged
        original_get_for_update = uow.ingestion_jobs.get_for_update

        async def list_sources_before_lock(
            ingestion_job_id: uuid.UUID,
            *,
            limit: int,
            offset: int,
        ) -> cabc.Sequence[IngestionJobSource]:
            """Record source work performed outside the ingestion-job lock."""
            nonlocal source_page_loaded
            source_page_loaded = True
            return await original_list(ingestion_job_id, limit=limit, offset=offset)

        async def lock_after_source_paging(
            ingestion_job_id: uuid.UUID,
        ) -> IngestionJob | None:
            """Verify the short reservation lock follows source paging."""
            assert source_page_loaded, "ingestion-job lock preceded source paging"
            return await original_get_for_update(ingestion_job_id)

        monkeypatch.setattr(
            uow.ingestion_job_sources,
            "list_for_job_paged",
            list_sources_before_lock,
        )
        monkeypatch.setattr(
            uow.ingestion_jobs,
            "get_for_update",
            lock_after_source_paging,
        )
        await materialise_episode_from_ingestion(
            uow,
            EpisodeMaterialisationRequest(
                ingestion_job_id=job.id,
                title="Bridgewater Futures",
                clock=_clock,
                uuid_factory=SequentialUuids(),
            ),
        )
