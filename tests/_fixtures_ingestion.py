"""Ingestion pipeline fixtures for integration tests."""

import asyncio
import datetime as dt
import typing as typ
import uuid

import pytest_asyncio

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from episodic.canonical.adapters.normalizer import InMemorySourceNormalizer
from episodic.canonical.adapters.resolver import HighestWeightConflictResolver
from episodic.canonical.adapters.weighting import DefaultWeightingStrategy
from episodic.canonical.domain import SeriesProfile
from episodic.canonical.ingestion_service import IngestionPipeline
from episodic.canonical.storage import SqlAlchemyUnitOfWork


@pytest_asyncio.fixture
async def series_profile_for_ingestion(
    session_factory: typ.Callable[[], AsyncSession],
) -> SeriesProfile:
    """Create and persist a series profile for ingestion integration tests.

    Parameters
    ----------
    session_factory : Callable[[], AsyncSession]
        Factory that returns an async SQLAlchemy session bound to the
        migrated test database.

    Returns
    -------
    SeriesProfile
        Persisted series profile instance used by ingestion integration
        tests.
    """
    now = dt.datetime.now(dt.UTC)
    profile = SeriesProfile(
        id=uuid.uuid4(),
        slug=f"test-series-{uuid.uuid4().hex[:8]}",
        title="Test Series",
        description=None,
        configuration={"tone": "neutral"},
        guardrails={},
        created_at=now,
        updated_at=now,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.series_profiles.add(profile)
        await uow.commit()
    return profile


@pytest_asyncio.fixture
async def ingestion_pipeline() -> IngestionPipeline:
    """Build the standard multi-source ingestion pipeline for tests.

    Parameters
    ----------
    None

    Returns
    -------
    IngestionPipeline
        The ``ingestion_pipeline`` fixture instance configured with
        ``InMemorySourceNormalizer``, ``DefaultWeightingStrategy``, and
        ``HighestWeightConflictResolver``.
    """
    # Yield control once so async fixture setup is consistently scheduled.
    await asyncio.sleep(0)

    return IngestionPipeline(
        normalizer=InMemorySourceNormalizer(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )
