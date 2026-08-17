"""Tests for optimistic episode TEI updates."""

import dataclasses as dc
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
from episodic.canonical.episode_errors import EpisodeRevisionConflictError
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.entity_mappers import _episode_to_record
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


def test_episode_revision_rejects_boolean(
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Boolean revisions must not pass as integers."""
    _, _, episode, _, _ = episode_fixture

    with pytest.raises(ValueError, match="positive integer"):
        dc.replace(episode, tei_revision=True)


def test_episode_content_hash_requires_string(
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Set content hashes must be strings before whitespace validation."""
    _, _, episode, _, _ = episode_fixture

    with pytest.raises(TypeError, match="must be a string"):
        dc.replace(episode, tei_content_hash=typ.cast("typ.Any", 42))


def test_episode_mapper_derives_tei_content_hash(
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Storage records derive their TEI hash from the mapped XML."""
    _, _, episode, _, _ = episode_fixture
    stale_episode = dc.replace(episode, tei_content_hash="sha256:stale")

    record = _episode_to_record(stale_episode)

    assert record.tei_content_hash == _tei_hash(episode.tei_xml), (
        f"record hash: {record.tei_content_hash!r}"
    )


@pytest.mark.parametrize(
    ("overrides", "error_type", "message"),
    [
        ({"tei_xml": 42}, TypeError, "tei_xml must be a string"),
        ({"qa_status": None}, ValueError, "qa_status must be set"),
        (
            {"last_generation_run_id": None},
            ValueError,
            "last_generation_run_id must be set",
        ),
        ({"expected_revision": True}, ValueError, "positive integer"),
    ],
)
def test_episode_tei_update_rejects_invalid_domain_values(
    overrides: dict[str, object],
    error_type: type[Exception],
    message: str,
) -> None:
    """TEI updates require typed content, provenance, and exact revisions."""
    values: dict[str, object] = {
        "tei_xml": "<TEI/>",
        "qa_status": QaStatus.SKIPPED,
        "last_generation_run_id": uuid.uuid7(),
        "expected_revision": 1,
    }
    values.update(overrides)

    with pytest.raises(error_type, match=message):
        EpisodeTeiUpdate(**typ.cast("typ.Any", values))


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
    session_factory: async_sessionmaker[AsyncSession],
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
    await _persist_episode_parents(session_factory, series, header)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
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

    assert updated.tei_xml == updated_xml, (
        f"expected updated TEI {updated_xml!r}, got {updated.tei_xml!r}"
    )
    assert updated.tei_revision == 2, (
        f"expected TEI revision 2, got {updated.tei_revision}"
    )
    assert updated.tei_content_hash == _tei_hash(updated_xml), (
        f"expected TEI hash {_tei_hash(updated_xml)!r}, "
        f"got {updated.tei_content_hash!r}"
    )
    assert updated.qa_status is QaStatus.SKIPPED, (
        f"expected skipped QA status, got {updated.qa_status!r}"
    )
    assert updated.last_generation_run_id == run.id, (
        f"expected generation run {run.id}, got {updated.last_generation_run_id}"
    )
    assert updated.updated_at == updated_at, (
        f"expected update time {updated_at!r}, got {updated.updated_at!r}"
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        fetched = await uow.episodes.get(episode.id)

    assert fetched is not None, f"expected episode {episode.id}, got {fetched!r}"
    assert fetched.tei_xml == updated_xml, (
        f"expected persisted TEI {updated_xml!r}, got {fetched.tei_xml!r}"
    )
    assert fetched.tei_revision == 2, (
        f"expected persisted revision 2, got {fetched.tei_revision}"
    )
    assert fetched.tei_content_hash == _tei_hash(updated_xml), (
        f"expected persisted hash {_tei_hash(updated_xml)!r}, "
        f"got {fetched.tei_content_hash!r}"
    )
    assert fetched.qa_status is QaStatus.SKIPPED, (
        f"expected persisted skipped QA status, got {fetched.qa_status!r}"
    )
    assert fetched.last_generation_run_id == run.id, (
        f"expected persisted run {run.id}, got {fetched.last_generation_run_id}"
    )


@pytest.mark.asyncio
async def test_episode_update_tei_keeps_compressed_storage_in_sync(
    session_factory: async_sessionmaker[AsyncSession],
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
    await _persist_episode_parents(session_factory, series, header)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
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

    async with session_factory() as session:
        result = await session.execute(
            sa.select(EpisodeRecord).where(EpisodeRecord.id == episode.id)
        )
        record = result.scalar_one()

    assert record.tei_xml == "__zstd__", (
        f"expected compressed-storage marker, got {record.tei_xml!r}"
    )
    assert record.tei_xml_zstd is not None, (
        f"expected compressed TEI bytes, got {record.tei_xml_zstd!r}"
    )
    assert record.tei_revision == 2, (
        f"expected compressed TEI revision 2, got {record.tei_revision}"
    )
    assert record.tei_content_hash == _tei_hash(updated_xml), (
        f"expected compressed TEI hash {_tei_hash(updated_xml)!r}, "
        f"got {record.tei_content_hash!r}"
    )
    assert record.qa_status is QaStatus.SKIPPED, (
        f"expected compressed record QA status skipped, got {record.qa_status!r}"
    )
    assert record.last_generation_run_id == run.id, (
        f"expected compressed record run {run.id}, got {record.last_generation_run_id}"
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        fetched = await uow.episodes.get(episode.id)

    assert fetched is not None, f"expected episode {episode.id}, got {fetched!r}"
    assert fetched.tei_xml == updated_xml, (
        "expected decompressed TEI length "
        f"{len(updated_xml)}, got {len(fetched.tei_xml)}"
    )


@pytest.mark.asyncio
async def test_episode_update_tei_rejects_stale_revision(
    session_factory: async_sessionmaker[AsyncSession],
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
    await _persist_episode_parents(session_factory, series, header)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.episodes.add(episode)
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(EpisodeRevisionConflictError):
            await uow.episodes.update(
                episode.id,
                update=EpisodeTeiUpdate(
                    tei_xml="<TEI>stale</TEI>",
                    qa_status=QaStatus.SKIPPED,
                    last_generation_run_id=run.id,
                    expected_revision=2,
                ),
            )
