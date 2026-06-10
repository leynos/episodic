"""Tests for py-pglite database fixtures."""

import asyncio
import typing as typ
from unittest import mock

import pytest
import sqlalchemy as sa

from tests.fixtures import database

if typ.TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncEngine


class _CountingSchemaResetLock:
    """Async context manager that records reset lock usage."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.enter_count = 0
        self.exit_count = 0
        self._active_count = 0
        self.max_active_count = 0

    async def __aenter__(self) -> _CountingSchemaResetLock:
        self.enter_count += 1
        await self._lock.acquire()
        self._active_count += 1
        self.max_active_count = max(self.max_active_count, self._active_count)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exit_count += 1
        self._active_count -= 1
        self._lock.release()


@pytest.mark.asyncio
async def test_reset_public_schema_serializes_concurrent_calls(
    pglite_engine: AsyncEngine,
) -> None:
    """Concurrent resets should leave one public schema and release the lock."""
    counting_lock = _CountingSchemaResetLock()

    with mock.patch.object(database, "_schema_reset_lock", counting_lock):
        await asyncio.gather(
            database._reset_public_schema(pglite_engine),
            database._reset_public_schema(pglite_engine),
        )

    async with pglite_engine.connect() as connection:
        result = await connection.execute(
            sa.text(
                "SELECT count(*) FROM information_schema.schemata "
                "WHERE schema_name = 'public'"
            )
        )

    assert result.scalar_one() == 1
    assert counting_lock.enter_count == 2
    assert counting_lock.exit_count == 2
    assert counting_lock.max_active_count == 1
