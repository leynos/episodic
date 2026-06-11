"""Database infrastructure fixtures (py-pglite, SQLAlchemy)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import typing as typ

import pytest
import pytest_asyncio
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc

from episodic.canonical.storage.alembic_helpers import apply_migrations
from episodic.canonical.storage.models import Base

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from py_pglite.sqlalchemy.manager_async import (  # type: ignore[import-untyped]
        SQLAlchemyAsyncPGliteManager,
    )
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

try:
    from py_pglite import PGliteConfig, PGliteManager  # type: ignore[import-untyped]

    _PGLITE_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _PGLITE_AVAILABLE = False


# Serialise concurrent schema resets under pytest-xdist. Workers sharing one
# py-pglite process must go through this lock before dropping `public`.
_schema_reset_lock = asyncio.Lock()


@pytest.fixture(scope="session")
def pglite_node_environment(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Return the session work root for py-pglite test processes."""
    if not _should_use_pglite():
        pytest.skip("EPISODIC_TEST_DB=sqlite disables py-pglite-backed fixtures.")

    return tmp_path_factory.mktemp("pglite-node-env")


def _should_use_pglite() -> bool:
    """Return True when tests should attempt py-pglite.

    If a non-SQLite backend is requested but py-pglite is unavailable,
    fail fast with a clear error instead of silently skipping tests.
    """
    allowed_values = {"sqlite", "pglite"}
    target = os.getenv("EPISODIC_TEST_DB", "pglite").lower()
    if target not in allowed_values:
        msg = (
            f"Unsupported EPISODIC_TEST_DB value: {target!r}. "
            f"Allowed values are: {', '.join(sorted(allowed_values))}."
        )
        raise RuntimeError(msg)
    if target == "sqlite":
        return False
    if target == "pglite" and not _PGLITE_AVAILABLE:
        msg = (
            "Database-backed tests requested via EPISODIC_TEST_DB="
            f"{target!r}, but py-pglite is not installed or unavailable. "
            "Install py-pglite (see docs/testing-sqlalchemy-with-pytest-and-"
            "py-pglite.md) or set EPISODIC_TEST_DB=sqlite."
        )
        raise RuntimeError(msg)
    return True


async def _wait_for_engine_ready(engine: AsyncEngine) -> None:
    """Wait for the helper-managed py-pglite engine to accept connections."""
    max_attempts = 30
    delay_seconds = 0.1
    for attempt in range(1, max_attempts + 1):
        try:
            async with engine.connect() as connection:
                await connection.execute(sa.text("SELECT 1"))
        except sa_exc.OperationalError as exc:
            if attempt == max_attempts:
                msg = (
                    f"py-pglite engine not ready after {max_attempts} "
                    f"attempts ({delay_seconds}s apart)"
                )
                raise RuntimeError(msg) from exc
            await asyncio.sleep(delay_seconds)
        else:
            return


async def _reset_public_schema(engine: AsyncEngine) -> None:
    """Reset the shared py-pglite database before applying migrations."""
    async with _schema_reset_lock, engine.begin() as connection:
        await connection.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(sa.text("CREATE SCHEMA public"))


@contextlib.asynccontextmanager
async def _pglite_sqlalchemy_manager(
    work_dir: Path,
) -> cabc.AsyncIterator[SQLAlchemyAsyncPGliteManager]:
    """Start a helper-backed py-pglite manager for SQLAlchemy tests."""
    if not _PGLITE_AVAILABLE:  # pragma: no cover - defensive guard
        msg = "py-pglite is not available for test fixtures."
        raise RuntimeError(msg)

    from py_pglite.sqlalchemy.manager_async import SQLAlchemyAsyncPGliteManager
    from sqlalchemy.pool import NullPool

    last_error: Exception | None = None
    for attempt in range(1, 4):
        attempt_work_dir = work_dir.with_name(f"{work_dir.name}-attempt-{attempt}")
        config = PGliteConfig(
            work_dir=attempt_work_dir,
            timeout=90,
        )
        manager = SQLAlchemyAsyncPGliteManager(config)
        try:
            manager.start()
            engine = typ.cast("AsyncEngine", manager.get_engine(poolclass=NullPool))
            await _wait_for_engine_ready(engine)
        except (RuntimeError, sa_exc.OperationalError) as exc:
            last_error = exc
            await manager.stop()
            continue

        try:
            yield manager
        finally:
            await manager.stop()
        return

    msg = "py-pglite failed to start after 3 attempts."
    raise RuntimeError(msg) from last_error


@contextlib.contextmanager
def temporary_drift_table() -> cabc.Iterator[sa.Table]:
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


@pytest_asyncio.fixture(scope="session")
async def pglite_sqlalchemy_manager(
    pglite_node_environment: Path,
) -> cabc.AsyncIterator[SQLAlchemyAsyncPGliteManager]:
    """Yield the session-scoped py-pglite SQLAlchemy manager.

    This is the shared py-pglite entry point for SQLAlchemy-backed tests in
    this repository. Prefer `session_factory`, `pglite_session`, or
    `migrated_engine` in tests unless you need lower-level manager access.
    """
    if not _should_use_pglite():
        pytest.skip("EPISODIC_TEST_DB=sqlite disables py-pglite-backed fixtures.")

    work_dir = pglite_node_environment / "server"
    async with _pglite_sqlalchemy_manager(work_dir) as manager:
        yield manager


@pytest_asyncio.fixture
async def pglite_engine(
    pglite_sqlalchemy_manager: SQLAlchemyAsyncPGliteManager,
) -> cabc.AsyncIterator[AsyncEngine]:
    """Yield an async SQLAlchemy engine provided by py-pglite's helper manager."""
    from sqlalchemy.pool import NullPool

    engine = typ.cast(
        "AsyncEngine", pglite_sqlalchemy_manager.get_engine(poolclass=NullPool)
    )
    await asyncio.sleep(0)
    yield engine


@pytest_asyncio.fixture
async def migrated_engine(
    pglite_engine: AsyncEngine,
) -> cabc.AsyncIterator[AsyncEngine]:
    """Yield a py-pglite engine with migrations applied."""
    await _reset_public_schema(pglite_engine)
    await apply_migrations(pglite_engine)
    yield pglite_engine


@pytest_asyncio.fixture
async def migrated_database_url(tmp_path: Path) -> cabc.AsyncIterator[str]:
    """Yield a migrated ephemeral database URL for runtime process tests."""
    if not _should_use_pglite():
        pytest.skip("EPISODIC_TEST_DB=sqlite disables py-pglite-backed fixtures.")

    if not _PGLITE_AVAILABLE:  # pragma: no cover - defensive guard
        msg = "py-pglite is not available for runtime test fixtures."
        raise RuntimeError(msg)

    from sqlalchemy.ext.asyncio import create_async_engine

    work_dir = tmp_path / "runtime-pglite"
    config = PGliteConfig(work_dir=work_dir)
    manager = PGliteManager(config)
    manager.start()
    try:
        database_url = config.get_connection_string()
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            await _wait_for_engine_ready(engine)
            await apply_migrations(engine)
        finally:
            await engine.dispose()
        yield database_url
    finally:
        if manager.is_running():
            manager.stop()


@pytest_asyncio.fixture
async def pglite_session(
    migrated_engine: AsyncEngine,
) -> cabc.AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session bound to py-pglite."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def session_factory(
    migrated_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Yield an async session factory bound to the migrated engine."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    await asyncio.sleep(0)
    return async_sessionmaker(
        migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
