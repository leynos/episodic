"""Concurrency-boundary tests for generation materialization."""

import asyncio
import typing as typ

import pytest
import sqlalchemy as sa

from episodic.canonical.generation_persistence import (
    EpisodeMaterialisationRequest,
    materialise_episode_from_ingestion,
)
from episodic.canonical.storage import (
    EpisodeRecord,
    IngestionJobRecord,
    SourceDocumentRecord,
    SqlAlchemyUnitOfWork,
    TeiHeaderRecord,
)
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
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source paging finishes before the materializer locks the job row."""
    _, job = await _persist_ready_job(session_factory)
    source_page_loaded = False

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
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


@pytest.mark.asyncio
async def test_materialisation_converges_under_two_session_contention(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Concurrent materialisation keeps one durable episode and source projection."""
    _, job = await _persist_ready_job(session_factory)
    barrier = asyncio.Barrier(2)

    async def materialise_in_independent_unit_of_work() -> uuid.UUID:
        """Start one materialisation attempt concurrently with its peer."""
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await barrier.wait()
            episode = await materialise_episode_from_ingestion(
                uow,
                EpisodeMaterialisationRequest(
                    ingestion_job_id=job.id,
                    title="Bridgewater Futures",
                    clock=_clock,
                    uuid_factory=SequentialUuids(),
                ),
            )
            return episode.id

    episode_ids = await asyncio.gather(
        materialise_in_independent_unit_of_work(),
        materialise_in_independent_unit_of_work(),
    )
    episode_id_set = set(episode_ids)
    assert len(episode_id_set) == 1, f"materialised episode ids: {episode_ids!r}"
    expected_episode_id = episode_id_set.pop()

    async with session_factory() as session:
        persisted_job = await session.scalar(
            sa.select(IngestionJobRecord).where(IngestionJobRecord.id == job.id)
        )
        episode_count = await session.scalar(sa.select(sa.func.count(EpisodeRecord.id)))
        header_count = await session.scalar(
            sa.select(sa.func.count(TeiHeaderRecord.id))
        )
        document_count = await session.scalar(
            sa.select(sa.func.count(SourceDocumentRecord.id))
        )

    assert persisted_job is not None, f"ingestion job not found: {job.id}"
    assert persisted_job.target_episode_id == expected_episode_id, (
        f"target episode id: {persisted_job.target_episode_id}; "
        f"expected: {expected_episode_id}"
    )
    assert episode_count == 1, f"episode count: {episode_count}"
    assert header_count == 1, f"TEI header count: {header_count}"
    assert document_count == 1, f"source document count: {document_count}"
