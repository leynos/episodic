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

import pytest
import pytest_asyncio
import sqlalchemy as sa

from episodic.canonical.storage.alembic_helpers import apply_migrations
from episodic.canonical.storage.models import Base

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

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
            yield engine
        finally:
            await engine.dispose()


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
