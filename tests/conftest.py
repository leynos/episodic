"""Pytest fixtures for database-backed tests.

These fixtures follow the py-pglite approach documented in
`docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.
"""

from __future__ import annotations

import contextlib
import os
import socket
import typing as typ

import pytest
import pytest_asyncio

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

try:
    from py_pglite import PGliteConfig, PGliteManager

    _PGLITE_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _PGLITE_AVAILABLE = False


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
        from sqlalchemy.ext.asyncio import create_async_engine

        url = (
            f"postgresql+asyncpg://postgres:postgres@{config.tcp_host}:"
            f"{config.tcp_port}/postgres"
        )
        engine = create_async_engine(url)
        try:
            yield engine
        finally:
            await engine.dispose()


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
async def pglite_session(
    pglite_engine: AsyncEngine,
) -> typ.AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session bound to py-pglite."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        pglite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
