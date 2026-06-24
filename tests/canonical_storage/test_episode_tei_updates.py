"""Tests for optimistic episode TEI updates."""

from __future__ import annotations

import datetime as dt
import hashlib
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.canonical.domain import (
    EpisodeTeiUpdate,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.episode_errors import EpisodeRevisionConflict
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.models import EpisodeRecord

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


def _tei_hash(tei_xml: str) -> str:
    """Return the persisted content hash for an episode TEI payload."""
    return f"sha256:{hashlib.sha256(tei_xml.encode()).hexdigest()}"


def _generation_run(episode: CanonicalEpisode) -> GenerationRun:
    """Return a generation run linked to an episode fixture."""
    return GenerationRun(
        id=uuid.uuid7(),
        episode_id=episode.id,
        source_bundle_id=uuid.uuid7(),
        actor="storage-test",
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={},
        configuration={},
        created_at=episode.created_at,
        updated_at=episode.updated_at,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="Storage test bypasses QA.",
    )


async def _persist_episode_parents(
    factory: async_sessionmaker[AsyncSession],
    series: SeriesProfile,
    header: TeiHeader,
) -> None:
    """Persist the parent rows required by an episode fixture."""
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()


@pytest.mark.asyncio
async def test_episode_update_tei_records_revision_and_generation_metadata(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Updating episode TEI should persist the no-QA generation metadata."""
    series, header, episode, _, _ = episode_fixture
    run = _generation_run(episode)
    updated_xml = "<TEI><text><body><p>Generated script.</p></body></text></TEI>"
    updated_at = dt.datetime(2026, 6, 24, 12, 0, tzinfo=dt.UTC)
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    await _persist_episode_parents(factory, series, header)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episodes.add(episode)
        await uow.generation_runs.create_run(run)
        updated = await uow.episodes.update(
            episode.id,
            update=EpisodeTeiUpdate(
                tei_xml=updated_xml,
                qa_status=QaStatus.SKIPPED,
                last_generation_run_id=run.id,
                expected_revision=1,
                updated_at=updated_at,
            ),
        )
        await uow.commit()

    assert updated.tei_xml == updated_xml
    assert updated.tei_revision == 2
    assert updated.tei_content_hash == _tei_hash(updated_xml)
    assert updated.qa_status is QaStatus.SKIPPED
    assert updated.last_generation_run_id == run.id
    assert updated.updated_at == updated_at

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.episodes.get(episode.id)

    assert fetched is not None
    assert fetched.tei_xml == updated_xml
    assert fetched.tei_revision == 2
    assert fetched.tei_content_hash == _tei_hash(updated_xml)
    assert fetched.qa_status is QaStatus.SKIPPED
    assert fetched.last_generation_run_id == run.id


@pytest.mark.asyncio
async def test_episode_update_tei_keeps_compressed_storage_in_sync(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Large updated TEI payloads should refresh compressed storage columns."""
    series, header, episode, _, _ = episode_fixture
    run = _generation_run(episode)
    updated_xml = "<TEI>" + ("generated episode " * 1200) + "</TEI>"
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    await _persist_episode_parents(factory, series, header)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episodes.add(episode)
        await uow.generation_runs.create_run(run)
        await uow.episodes.update(
            episode.id,
            update=EpisodeTeiUpdate(
                tei_xml=updated_xml,
                qa_status=QaStatus.SKIPPED,
                last_generation_run_id=run.id,
                expected_revision=1,
            ),
        )
        await uow.commit()

    async with factory() as session:
        result = await session.execute(
            sa.select(EpisodeRecord).where(EpisodeRecord.id == episode.id)
        )
        record = result.scalar_one()

    assert record.tei_xml == "__zstd__"
    assert record.tei_xml_zstd is not None
    assert record.tei_revision == 2
    assert record.tei_content_hash == _tei_hash(updated_xml)
    assert record.qa_status is QaStatus.SKIPPED
    assert record.last_generation_run_id == run.id

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.episodes.get(episode.id)

    assert fetched is not None
    assert fetched.tei_xml == updated_xml


@pytest.mark.asyncio
async def test_episode_update_tei_rejects_stale_revision(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Updating with a stale expected revision should raise a conflict."""
    series, header, episode, _, _ = episode_fixture
    run = _generation_run(episode)
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    await _persist_episode_parents(factory, series, header)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episodes.add(episode)
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(EpisodeRevisionConflict):
            await uow.episodes.update(
                episode.id,
                update=EpisodeTeiUpdate(
                    tei_xml="<TEI>stale</TEI>",
                    qa_status=QaStatus.SKIPPED,
                    last_generation_run_id=run.id,
                    expected_revision=2,
                ),
            )
