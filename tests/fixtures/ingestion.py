"""Ingestion pipeline and seed-data fixtures."""

import typing as typ
import uuid

import pytest
import pytest_asyncio

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import SeriesProfile
    from episodic.canonical.ingestion_service import IngestionPipeline


@pytest_asyncio.fixture
async def series_profile_for_ingestion(
    session_factory: async_sessionmaker[AsyncSession],
) -> SeriesProfile:
    """Create and persist a series profile for ingestion integration tests.

    Parameters
    ----------
    session_factory : async_sessionmaker[AsyncSession]
        Async SQLAlchemy session factory bound to the migrated test database.

    Returns
    -------
    SeriesProfile
        Persisted series profile instance used by ingestion integration
        tests.
    """
    import datetime as dt

    from episodic.canonical.domain import SeriesProfile
    from episodic.canonical.storage import SqlAlchemyUnitOfWork

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


@pytest.fixture
def ingestion_pipeline() -> IngestionPipeline:
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
    from episodic.canonical.adapters.normalizer import InMemorySourceNormalizer
    from episodic.canonical.adapters.resolver import HighestWeightConflictResolver
    from episodic.canonical.adapters.weighting import DefaultWeightingStrategy
    from episodic.canonical.ingestion_service import IngestionPipeline

    return IngestionPipeline(
        normalizer=InMemorySourceNormalizer(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )
