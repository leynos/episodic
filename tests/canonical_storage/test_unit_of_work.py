"""Unit tests for canonical storage unit-of-work behaviour.

Examples
--------
Run the unit-of-work tests:

>>> pytest tests/canonical_storage/test_unit_of_work.py
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import SeriesProfile
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
