"""Pytest fixtures for database-backed tests.

These fixtures follow the py-pglite approach documented in
`docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.

Examples
--------
Run database-backed tests with py-pglite:

>>> EPISODIC_TEST_DB=pglite pytest -k canonical
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import typing as typ
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc

from episodic.canonical.storage.alembic_helpers import apply_migrations
from episodic.canonical.storage.models import Base

if typ.TYPE_CHECKING:
    from pathlib import Path

    from falcon import testing
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from episodic.canonical.domain import SeriesProfile
    from episodic.canonical.ingestion_service import IngestionPipeline

try:
    from py_pglite import PGliteConfig, PGliteManager

    _PGLITE_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _PGLITE_AVAILABLE = False


def _should_use_pglite() -> bool:
    """Return True when tests should attempt py-pglite.

    If a non-SQLite backend is requested but py-pglite is unavailable,
    fail fast with a clear error instead of silently skipping tests.
    """
    target = os.getenv("EPISODIC_TEST_DB", "pglite").lower()
    if target == "sqlite":
        return False
    if not _PGLITE_AVAILABLE:
        msg = (
            "Database-backed tests requested via EPISODIC_TEST_DB="
            f"{target!r}, but py-pglite is not installed or unavailable. "
            "Install py-pglite (see docs/testing-sqlalchemy-with-pytest-and-"
            "py-pglite.md) or set EPISODIC_TEST_DB=sqlite."
        )
        raise RuntimeError(msg)
    return True


@contextlib.asynccontextmanager
async def _pglite_engine(tmp_path: Path) -> typ.AsyncIterator[AsyncEngine]:
    """Start a py-pglite Postgres and yield an async engine bound to it."""
    if not _PGLITE_AVAILABLE:  # pragma: no cover - defensive guard
        msg = "py-pglite is not available for test fixtures."
        raise RuntimeError(msg)

    work_dir = tmp_path / "pglite"
    config = PGliteConfig(work_dir=work_dir)

    with PGliteManager(config):
        from sqlalchemy.ext.asyncio import create_async_engine

        dsn = config.get_connection_string()
        engine = create_async_engine(dsn, pool_pre_ping=True)
        try:
            await _wait_for_engine_ready(engine)
            yield engine
        finally:
            await engine.dispose()


async def _wait_for_engine_ready(engine: AsyncEngine) -> None:
    """Wait for py-pglite to accept SQLAlchemy connections.

    Under xdist parallel workers, py-pglite can report startup before the
    socket is ready for the first connection. This retry keeps tests stable.
    """
    max_attempts = 30
    delay_seconds = 0.1
    for attempt in range(1, max_attempts + 1):
        try:
            async with engine.connect() as connection:
                await connection.execute(sa.text("SELECT 1"))
        except sa_exc.OperationalError:
            if attempt == max_attempts:
                raise
            await asyncio.sleep(delay_seconds)
        else:
            return


@contextlib.contextmanager
def temporary_drift_table() -> typ.Iterator[sa.Table]:
    """Add a temporary table to Base.metadata and remove it on exit.

    This helper is shared between the unit tests and BDD steps that
    verify schema drift detection against an unmigrated table.
    """
    table = sa.Table(
        "_test_drift_table",
        Base.metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    try:
        yield table
    finally:
        Base.metadata.remove(table)


@pytest_asyncio.fixture
async def pglite_engine(tmp_path: Path) -> typ.AsyncIterator[AsyncEngine]:
    """Yield an async engine backed by py-pglite Postgres."""
    if not _should_use_pglite():
        pytest.skip("EPISODIC_TEST_DB=sqlite disables py-pglite-backed fixtures.")

    async with _pglite_engine(tmp_path) as engine:
        yield engine


@pytest.fixture
def _function_scoped_runner() -> typ.Iterator[asyncio.Runner]:
    """Provide a function-scoped asyncio.Runner for sync BDD steps."""
    with asyncio.Runner() as runner:
        yield runner


@pytest_asyncio.fixture
async def migrated_engine(
    pglite_engine: AsyncEngine,
) -> typ.AsyncIterator[AsyncEngine]:
    """Yield a py-pglite engine with migrations applied."""
    await apply_migrations(pglite_engine)
    yield pglite_engine


@pytest.fixture
def session_factory(
    migrated_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Yield an async session factory bound to the migrated engine."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(
        migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


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

    from episodic.canonical.adapters.normalizer import InMemorySourceNormalizer
    from episodic.canonical.adapters.resolver import HighestWeightConflictResolver
    from episodic.canonical.adapters.weighting import DefaultWeightingStrategy
    from episodic.canonical.ingestion_service import IngestionPipeline

    return IngestionPipeline(
        normalizer=InMemorySourceNormalizer(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )


@pytest_asyncio.fixture
async def pglite_session(
    migrated_engine: AsyncEngine,
) -> typ.AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session bound to py-pglite."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def canonical_api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> testing.TestClient:
    """Build a Falcon test client for profile/template REST endpoints."""
    from falcon import testing

    from episodic.api import create_app
    from episodic.canonical.storage import SqlAlchemyUnitOfWork

    app = create_app(lambda: SqlAlchemyUnitOfWork(session_factory))
    return testing.TestClient(app)
