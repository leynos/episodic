"""Pytest fixtures for database-backed tests.

These fixtures follow the py-pglite approach documented in
`docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.
"""

from __future__ import annotations

import contextlib
import os
import socket
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


class _AsyncpgProxy:
    """Proxy asyncpg connections to enforce close timeouts."""

    def __init__(self, connection: _AsyncpgConnection) -> None:
        self._connection = connection

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)

    async def close(self, *, timeout: float | None = None) -> None:
        try:
            await self._connection.close(timeout=timeout or 2)
        except Exception:  # noqa: BLE001
            self._connection.terminate()


class _AsyncpgConnection(typ.Protocol):
    """Minimal asyncpg connection surface required for cleanup."""

    async def close(self, *, timeout: float | None = None) -> None: ...

    def terminate(self) -> None: ...


def _should_use_pglite() -> bool:
    """Return True when tests should attempt py-pglite."""
    target = os.getenv("EPISODIC_TEST_DB", "pglite").lower()
    return target != "sqlite" and _PGLITE_AVAILABLE


def _find_free_port() -> int:
    """Find an available TCP port for a temporary Postgres instance."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.asynccontextmanager
async def _pglite_engine(tmp_path: Path) -> typ.AsyncIterator[AsyncEngine]:
    """Start a py-pglite Postgres and yield an async engine bound to it."""
    if not _PGLITE_AVAILABLE:  # pragma: no cover - defensive guard
        msg = "py-pglite is not available for test fixtures."
        raise RuntimeError(msg)

    port = _find_free_port()
    work_dir = tmp_path / "pglite"
    config = PGliteConfig(
        use_tcp=True,
        tcp_host="127.0.0.1",
        tcp_port=port,
        work_dir=work_dir,
    )

    with PGliteManager(config):
        import asyncpg
        from sqlalchemy.ext.asyncio import create_async_engine

        dsn = config.get_asyncpg_uri()

        async def async_creator() -> asyncpg.Connection:
            connection = await asyncpg.connect(dsn=dsn, ssl=False, timeout=5)
            return typ.cast("asyncpg.Connection", _AsyncpgProxy(connection))

        url = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(
            url,
            async_creator=async_creator,
            pool_pre_ping=True,
        )
        try:
            yield engine
        finally:
            await engine.dispose()


def _alembic_config(database_url: str) -> Config:
    """Create an Alembic configuration for test migrations."""
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
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
        pytest.skip(
            "py-pglite unavailable. "
            "See docs/testing-sqlalchemy-with-pytest-and-py-pglite.md."
        )

    engine_cm = _pglite_engine(tmp_path)
    engine = await engine_cm.__aenter__()
    try:
        yield engine
    finally:
        await engine_cm.__aexit__(None, None, None)


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
