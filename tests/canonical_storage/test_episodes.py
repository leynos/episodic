"""Unit tests for canonical storage episode repositories.

Examples
--------
Run the episode repository tests:

>>> pytest tests/canonical_storage/test_episodes.py
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import pytest
import sqlalchemy as sa

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


@pytest.mark.asyncio
async def test_can_persist_episode_with_header(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Episodes persist with linked TEI headers and ingestion metadata."""
    series, header, episode, job, source = episode_fixture
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
async def test_episode_large_tei_xml_round_trip_uses_compressed_storage(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Large episode TEI payloads are stored compressed and read as plain text."""
    series, header, episode, _, _ = episode_fixture
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
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
    precompressed_tei_xml_payload: str,
) -> None:
    """Pre-compressed episode payload strings remain in plain-text storage."""
    series, header, episode, _, _ = episode_fixture
    episode = dc.replace(episode, tei_xml=precompressed_tei_xml_payload)
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
    assert record.tei_xml == precompressed_tei_xml_payload, (
        "Expected text column to keep the original pre-compressed payload."
    )
    assert record.tei_xml != "__zstd__", (
        "Expected non-compressed rows to avoid the compression sentinel."
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.episodes.get(episode.id)

    assert fetched is not None, "Expected pre-compressed episode row to be retrievable."
    assert fetched.tei_xml == precompressed_tei_xml_payload, (
        "Expected read path to return stored uncompressed episode payload."
    )


@pytest.mark.asyncio
async def test_episode_get_remains_compatible_with_legacy_uncompressed_rows(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Episode reads remain compatible with rows written before compression."""
    series, header, episode, _, _ = episode_fixture
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
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Corrupt compressed episode payloads raise a decode error on read."""
    series, header, episode, _, _ = episode_fixture
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
