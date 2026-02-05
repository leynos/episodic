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
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config

from alembic import command

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection
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


def _alembic_config(database_url: str) -> Config:
    """Create an Alembic configuration for test migrations."""
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    # ConfigParser interpolates percent signs, so escape them in URLs.
    safe_url = database_url.replace("%", "%%")
    config.set_main_option("sqlalchemy.url", safe_url)
    return config


async def _apply_migrations(engine: AsyncEngine) -> None:
    """Apply Alembic migrations against the provided engine."""
    config = _alembic_config(str(engine.url))

    async with engine.begin() as connection:
        await connection.run_sync(_run_migrations, config)


def _run_migrations(connection: Connection, config: Config) -> None:
    """Run Alembic migrations in a sync context."""
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


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
    await _apply_migrations(pglite_engine)
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
