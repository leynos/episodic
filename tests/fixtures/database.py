"""Database infrastructure fixtures (py-pglite, SQLAlchemy).

The py-pglite Node runtime plumbing these fixtures build on lives in
:mod:`tests.fixtures.pglite_runtime`, which owns the session Node directory,
the shared module tree, and the availability probe.
"""

import asyncio
import contextlib
import pathlib
import shutil
import tempfile
import typing as typ
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc

from episodic.canonical.storage.alembic_helpers import apply_migrations
from episodic.canonical.storage.models import Base
from tests.fixtures.pglite_runtime import (
    PGLITE_AVAILABLE,
    PGLITE_START_ATTEMPTS,
    pglite_node_environment,
    pglite_node_modules,
    prepare_pglite_work_dir,
    should_use_pglite,
)

# This module is loaded as a pytest plugin unconditionally, so it has to import
# when the optional py-pglite dependency is absent. Every fixture below that
# reaches for these names checks `PGLITE_AVAILABLE` first.
with contextlib.suppress(ModuleNotFoundError):  # pragma: no cover - optional dependency
    from py_pglite import (  # type: ignore[import-untyped]  # py-pglite does not publish type information for this optional test dependency.
        PGliteConfig,
        PGliteManager,
    )

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from py_pglite.sqlalchemy.manager_async import (  # type: ignore[import-untyped]  # py-pglite does not publish type information for this optional test dependency.
        SQLAlchemyAsyncPGliteManager,
    )
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# Re-exported so the py-pglite fixtures stay importable from this module, which
# is the pytest plugin registered by the root conftest.
__all__ = [
    "PGLITE_AVAILABLE",
    "PGLITE_START_ATTEMPTS",
    "pglite_node_environment",
    "pglite_node_modules",
    "prepare_pglite_work_dir",
    "should_use_pglite",
]


# Serialise concurrent schema resets under pytest-xdist. Workers sharing one
# py-pglite process must go through this lock before dropping `public`.
_schema_reset_lock = asyncio.Lock()


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
    if not PGLITE_AVAILABLE:  # pragma: no cover - defensive guard
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

    Yields
    ------
    sa.Table
        Temporary SQLAlchemy table attached to ``Base.metadata``.
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

    Yields
    ------
    SQLAlchemyAsyncPGliteManager
        Running manager shared by the SQLAlchemy-backed test session.
    """
    if not should_use_pglite():
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


async def _start_migrated_pglite(
    work_dir: Path,
    socket_dir: Path,
) -> tuple[PGliteManager, str]:
    """Start one migrated py-pglite server and return it with its URL.

    Parameters
    ----------
    work_dir : pathlib.Path
        Directory py-pglite runs the server from, holding the shared
        ``node_modules`` link.
    socket_dir : pathlib.Path
        Directory for this server's Unix socket.

    Returns
    -------
    tuple[PGliteManager, str]
        The running manager and a migrated SQLAlchemy connection URL.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    config = PGliteConfig(
        work_dir=work_dir,
        socket_path=str(socket_dir / ".s.PGSQL.5432"),
        timeout=90,
    )
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
    except BaseException:
        manager.stop()
        raise
    return manager, database_url


@pytest_asyncio.fixture
async def migrated_database_url(
    tmp_path: Path,
    pglite_node_modules: Path,
) -> cabc.AsyncIterator[str]:
    """Yield a migrated ephemeral database URL for runtime process tests.

    The server is started with retries because py-pglite's own startup is
    timing-sensitive, but the retry loop finishes before the value is
    yielded: an exception raised by the test body must reach pytest rather
    than be mistaken for a failed attempt.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Per-test directory holding this server's work directory.
    pglite_node_modules : pathlib.Path
        Session directory whose modules are linked into the work directory.

    Yields
    ------
    str
        SQLAlchemy URL for a migrated database, served for one test.

    Raises
    ------
    RuntimeError
        If py-pglite is unavailable, or the server never serves a migrated
        database within ``PGLITE_START_ATTEMPTS`` attempts.
    """
    if not should_use_pglite():
        pytest.skip("EPISODIC_TEST_DB=sqlite disables py-pglite-backed fixtures.")

    if not PGLITE_AVAILABLE:  # pragma: no cover - defensive guard
        msg = "py-pglite is not available for runtime test fixtures."
        raise RuntimeError(msg)

    work_dir = prepare_pglite_work_dir(pglite_node_modules, tmp_path / "runtime-pglite")
    # A socket path unique to this work directory keeps concurrently running
    # py-pglite servers from colliding, and is why the module tree is shared
    # as a link rather than the directory itself. `mkdtemp` already creates
    # the directory owner-only, matching py-pglite's own socket directory.
    socket_dir = pathlib.Path(
        tempfile.mkdtemp(prefix=f"py-pglite-{uuid.uuid4().hex[:8]}-")
    )

    last_error: Exception | None = None
    manager: PGliteManager | None = None
    database_url = ""
    for _attempt in range(1, PGLITE_START_ATTEMPTS + 1):
        try:
            manager, database_url = await _start_migrated_pglite(work_dir, socket_dir)
        except (RuntimeError, OSError, sa_exc.OperationalError) as exc:
            last_error = exc
            continue
        break

    if manager is None:
        shutil.rmtree(socket_dir, ignore_errors=True)
        msg = (
            "py-pglite failed to serve a migrated database after "
            f"{PGLITE_START_ATTEMPTS} attempts"
        )
        raise RuntimeError(msg) from last_error

    try:
        yield database_url
    finally:
        if manager.is_running():
            manager.stop()
        shutil.rmtree(socket_dir, ignore_errors=True)


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
