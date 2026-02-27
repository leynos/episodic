"""Unit tests for canonical storage series profile repositories.

Examples
--------
Run the series profile repository tests:

>>> pytest tests/canonical_storage/test_series_profiles.py
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
from sqlalchemy import exc as sa_exc

from episodic.canonical.domain import SeriesProfile
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
