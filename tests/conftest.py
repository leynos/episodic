"""Residual pytest fixtures for database-backed test infrastructure.

These residual fixtures follow the py-pglite approach documented in
`docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.

Examples
--------
Run database-backed tests with py-pglite:

>>> EPISODIC_TEST_DB=pglite pytest -k canonical
"""

import asyncio
import contextlib
import dataclasses as dc
import os
import typing as typ

import pytest
import pytest_asyncio
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc

from episodic.canonical.storage.alembic_helpers import apply_migrations
from episodic.canonical.storage.models import Base

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid
    from pathlib import Path

    from _fixtures_binding_resolution import BindingFixtures
    from falcon import testing
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        EpisodeTemplate,
        IngestionJob,
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
        SeriesProfile,
    )
    from episodic.canonical.ports import CanonicalUnitOfWork

pytest_plugins: list[str] = [
    "_fixtures_llm",
    "_fixtures_ingestion",
    "_fixtures_binding_resolution",
]


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


@dc.dataclass(frozen=True, slots=True)
class _SnapshotTestFixtures:
    uow: CanonicalUnitOfWork
    episode: CanonicalEpisode
    document: ReferenceDocument
    revision_v1: ReferenceDocumentRevision
    series: SeriesProfile
    job: IngestionJob
    reference_binding: ReferenceBinding


@pytest_asyncio.fixture
async def binding_snapshot_fixtures(
    uow_with_binding_fixtures: BindingFixtures,
    binding_snapshot_job: IngestionJob,
    binding_snapshot_reference_binding: ReferenceBinding,
) -> _SnapshotTestFixtures:
    """Bundle all snapshot-test domain fixtures into a single object."""
    await asyncio.sleep(0)
    return _SnapshotTestFixtures(
        uow=uow_with_binding_fixtures["uow"],
        episode=uow_with_binding_fixtures["episode_early"],
        document=uow_with_binding_fixtures["doc"],
        revision_v1=uow_with_binding_fixtures["revision_v1"],
        series=uow_with_binding_fixtures["series"],
        job=binding_snapshot_job,
        reference_binding=binding_snapshot_reference_binding,
    )


async def create_episode_template_for_binding_tests(
    uow: CanonicalUnitOfWork, series_id: uuid.UUID, now: dt.datetime
) -> EpisodeTemplate:
    """Create, persist, commit, and return an episode template for testing."""
    from _fixtures_binding_resolution import (
        create_episode_template_for_binding_tests as _create_template,
    )

    return await _create_template(uow, series_id, now)
