"""Unit tests for canonical storage repositories.

Examples
--------
Run the repository test suite:

>>> pytest tests/test_canonical_storage.py
"""

from __future__ import annotations

import base64
import dataclasses as dc
import datetime as dt
import typing as typ
import uuid
from compression import zstd

import pytest
import sqlalchemy as sa
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
from episodic.canonical.storage.models import EpisodeRecord, TeiHeaderRecord

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


def _build_precompressed_tei_xml_payload() -> str:
    """Return deterministic TEI payload that remains below compression threshold."""
    seed_bytes = bytes(range(256))
    precompressed_body = base64.b64encode(zstd.compress(seed_bytes)).decode("ascii")
    payload = f"<TEI>{precompressed_body}</TEI>"
    assert len(payload.encode("utf-8")) < 1024, (
        "Expected test payload to remain below default compression threshold."
    )
    return payload


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


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_entity(session_factory: object) -> None:
    """Repository get() returns None for a non-existent identifier."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        result = await uow.series_profiles.get(uuid.uuid4())

    assert result is None, "Expected None when the entity does not exist."


@pytest.mark.asyncio
async def test_uow_rollback_discards_uncommitted_changes(
    session_factory: object,
) -> None:
    """Rollback discards uncommitted changes."""
    now = dt.datetime.now(dt.UTC)
    profile = SeriesProfile(
        id=uuid.uuid4(),
        slug="rollback-test",
        title="Rollback Test",
        description=None,
        configuration={},
        created_at=now,
        updated_at=now,
    )
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(profile)
        await uow.rollback()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        result = await uow.series_profiles.get(profile.id)

    assert result is None, "Expected rollback to discard the uncommitted profile."


@pytest.mark.asyncio
async def test_uow_rolls_back_on_exception(session_factory: object) -> None:
    """UoW context manager rolls back on unhandled exception."""
    now = dt.datetime.now(dt.UTC)
    profile = SeriesProfile(
        id=uuid.uuid4(),
        slug="exception-test",
        title="Exception Test",
        description=None,
        configuration={},
        created_at=now,
        updated_at=now,
    )
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async def _add_and_raise() -> None:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            await uow.series_profiles.add(profile)
            msg = "Simulated failure."
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError):
        await _add_and_raise()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        result = await uow.series_profiles.get(profile.id)

    assert result is None, "Expected exception to trigger rollback."


@pytest.mark.asyncio
async def test_source_document_weight_check_constraint(session_factory: object) -> None:
    """Weight check constraint rejects values outside [0, 1]."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, job, _ = _episode_fixture(now)
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


@pytest.mark.asyncio
async def test_approval_event_fk_constraint(session_factory: object) -> None:
    """Approval event foreign key rejects non-existent episode."""
    now = dt.datetime.now(dt.UTC)
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        event = ApprovalEvent(
            id=uuid.uuid4(),
            episode_id=uuid.uuid4(),
            actor="test@example.com",
            from_state=None,
            to_state=ApprovalState.DRAFT,
            note="Orphan event.",
            payload={},
            created_at=now,
        )
        await uow.approval_events.add(event)
        with pytest.raises(
            sa_exc.IntegrityError,
            match=r"foreign key|FOREIGN KEY|fk|violates",
        ):
            await uow.commit()


@pytest.mark.asyncio
async def test_tei_header_round_trip(session_factory: object) -> None:
    """TEI header round-trips through add and get."""
    now = dt.datetime.now(dt.UTC)
    header = TeiHeader(
        id=uuid.uuid4(),
        title="Round Trip Header",
        payload={"file_desc": {"title": "Round Trip"}},
        raw_xml="<TEI>round trip</TEI>",
        created_at=now,
        updated_at=now,
    )
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.tei_headers.add(header)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.tei_headers.get(header.id)

    assert fetched is not None, "Expected the TEI header to persist."
    assert fetched.title == header.title, "Expected the title to round-trip."
    assert fetched.payload == header.payload, "Expected the payload to round-trip."
    assert fetched.raw_xml == header.raw_xml, "Expected the raw XML to round-trip."


@pytest.mark.asyncio
async def test_tei_header_large_raw_xml_round_trip_uses_compressed_storage(
    session_factory: object,
) -> None:
    """Large TEI header payloads are stored compressed and read as plain text."""
    now = dt.datetime.now(dt.UTC)
    raw_xml = "<TEI>" + ("x" * 4096) + "</TEI>"
    header = TeiHeader(
        id=uuid.uuid4(),
        title="Compressed Header",
        payload={"file_desc": {"title": "Compressed Header"}},
        raw_xml=raw_xml,
        created_at=now,
        updated_at=now,
    )
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.tei_headers.add(header)
        await uow.commit()

    async with factory() as session:
        result = await session.execute(
            sa.select(TeiHeaderRecord).where(TeiHeaderRecord.id == header.id)
        )
        record = result.scalar_one()

    assert record.raw_xml_zstd is not None, (
        "Expected large TEI header XML to persist in compressed storage."
    )
    assert record.raw_xml == "__zstd__", (
        "Expected text column to store the compression sentinel marker."
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.tei_headers.get(header.id)

    assert fetched is not None, "Expected compressed TEI header to be retrievable."
    assert fetched.raw_xml == raw_xml, (
        "Expected TEI header read path to transparently decompress payloads."
    )


@pytest.mark.asyncio
async def test_tei_header_get_remains_compatible_with_legacy_uncompressed_rows(
    session_factory: object,
) -> None:
    """TEI header reads remain compatible with rows written before compression."""
    now = dt.datetime.now(dt.UTC)
    record = TeiHeaderRecord(
        id=uuid.uuid4(),
        title="Legacy Header",
        payload={"file_desc": {"title": "Legacy Header"}},
        raw_xml="<TEI>legacy-row</TEI>",
        raw_xml_zstd=None,
        created_at=now,
        updated_at=now,
    )
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with factory() as session:
        session.add(record)
        await session.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.tei_headers.get(record.id)

    assert fetched is not None, "Expected legacy TEI header row to remain readable."
    assert fetched.raw_xml == "<TEI>legacy-row</TEI>", (
        "Expected uncompressed legacy TEI XML to round-trip unchanged."
    )


@pytest.mark.asyncio
async def test_tei_header_get_raises_for_corrupt_compressed_payload(
    session_factory: object,
) -> None:
    """Corrupt compressed TEI header payloads raise a decode error on read."""
    now = dt.datetime.now(dt.UTC)
    record = TeiHeaderRecord(
        id=uuid.uuid4(),
        title="Corrupt Header",
        payload={"file_desc": {"title": "Corrupt Header"}},
        raw_xml="__zstd__",
        raw_xml_zstd=b"definitely-not-zstd",
        created_at=now,
        updated_at=now,
    )
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with factory() as session:
        session.add(record)
        await session.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(ValueError, match="decompress"):
            await uow.tei_headers.get(record.id)


@pytest.mark.asyncio
async def test_ingestion_job_round_trip(session_factory: object) -> None:
    """Ingestion job round-trips through add and get."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, job, _ = _episode_fixture(now)
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


@pytest.mark.asyncio
async def test_episode_large_tei_xml_round_trip_uses_compressed_storage(
    session_factory: object,
) -> None:
    """Large episode TEI payloads are stored compressed and read as plain text."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, _, _ = _episode_fixture(now)
    large_tei_xml = "<TEI>" + ("episode " * 1200) + "</TEI>"
    episode = dc.replace(episode, tei_xml=large_tei_xml)
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episodes.add(episode)
        await uow.commit()

    async with factory() as session:
        result = await session.execute(
            sa.select(EpisodeRecord).where(EpisodeRecord.id == episode.id)
        )
        record = result.scalar_one()

    assert record.tei_xml_zstd is not None, (
        "Expected large episode TEI XML to persist in compressed storage."
    )
    assert record.tei_xml == "__zstd__", (
        "Expected episode text column to store the compression sentinel marker."
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.episodes.get(episode.id)

    assert fetched is not None, "Expected compressed episode row to be retrievable."
    assert fetched.tei_xml == large_tei_xml, (
        "Expected episode read path to transparently decompress payloads."
    )


@pytest.mark.asyncio
async def test_episode_precompressed_tei_xml_round_trip(
    session_factory: object,
) -> None:
    """Pre-compressed episode payload strings remain in plain-text storage."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, _, _ = _episode_fixture(now)
    precompressed_tei_xml = _build_precompressed_tei_xml_payload()
    episode = dc.replace(episode, tei_xml=precompressed_tei_xml)
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episodes.add(episode)
        await uow.commit()

    async with factory() as session:
        result = await session.execute(
            sa.select(EpisodeRecord).where(EpisodeRecord.id == episode.id)
        )
        record = result.scalar_one()

    assert record.tei_xml_zstd is None, (
        "Expected below-threshold episode payloads to skip compressed storage."
    )
    assert record.tei_xml == precompressed_tei_xml, (
        "Expected text column to keep the original pre-compressed payload."
    )
    assert record.tei_xml != "__zstd__", (
        "Expected non-compressed rows to avoid the compression sentinel."
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.episodes.get(episode.id)

    assert fetched is not None, "Expected pre-compressed episode row to be retrievable."
    assert fetched.tei_xml == precompressed_tei_xml, (
        "Expected read path to return stored uncompressed episode payload."
    )


@pytest.mark.asyncio
async def test_episode_get_remains_compatible_with_legacy_uncompressed_rows(
    session_factory: object,
) -> None:
    """Episode reads remain compatible with rows written before compression."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, _, _ = _episode_fixture(now)
    legacy_tei_xml = "<TEI>legacy-episode</TEI>"
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()

    async with factory() as session:
        session.add(
            EpisodeRecord(
                id=episode.id,
                series_profile_id=episode.series_profile_id,
                tei_header_id=episode.tei_header_id,
                title=episode.title,
                tei_xml=legacy_tei_xml,
                tei_xml_zstd=None,
                status=episode.status,
                approval_state=episode.approval_state,
                created_at=episode.created_at,
                updated_at=episode.updated_at,
            )
        )
        await session.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.episodes.get(episode.id)

    assert fetched is not None, "Expected legacy episode row to remain readable."
    assert fetched.tei_xml == legacy_tei_xml, (
        "Expected uncompressed legacy episode TEI XML to round-trip unchanged."
    )


@pytest.mark.asyncio
async def test_episode_get_raises_for_corrupt_compressed_payload(
    session_factory: object,
) -> None:
    """Corrupt compressed episode payloads raise a decode error on read."""
    now = dt.datetime.now(dt.UTC)
    series, header, episode, _, _ = _episode_fixture(now)
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()

    async with factory() as session:
        session.add(
            EpisodeRecord(
                id=episode.id,
                series_profile_id=episode.series_profile_id,
                tei_header_id=episode.tei_header_id,
                title=episode.title,
                tei_xml="__zstd__",
                tei_xml_zstd=b"corrupt-zstd-payload",
                status=episode.status,
                approval_state=episode.approval_state,
                created_at=episode.created_at,
                updated_at=episode.updated_at,
            )
        )
        await session.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(ValueError, match="decompress"):
            await uow.episodes.get(episode.id)


@pytest.mark.asyncio
async def test_list_for_episode_returns_empty_for_unknown(
    session_factory: object,
) -> None:
    """Listing approval events for a non-existent episode returns empty."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        events = await uow.approval_events.list_for_episode(uuid.uuid4())

    assert events == [], "Expected an empty list for a missing episode."
