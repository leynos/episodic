"""Unit tests for canonical storage TEI header repositories.

Examples
--------
Run the TEI header repository tests:

>>> pytest tests/canonical_storage/test_tei_headers.py
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.canonical.domain import TeiHeader
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.models import TeiHeaderRecord

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
