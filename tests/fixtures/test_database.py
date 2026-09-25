"""Tests for py-pglite database fixtures."""

import asyncio
import typing as typ
from unittest import mock

import pytest
import sqlalchemy as sa

from tests.fixtures import database

if typ.TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncEngine


class TestPreparePgliteWorkDir:
    """Reuse of the session-primed py-pglite Node modules."""

    def test_links_the_session_modules_instead_of_reinstalling(
        self, tmp_path: Path
    ) -> None:
        """Each work directory points at the primed modules."""
        source = tmp_path / "npm-seed"
        (source / "node_modules" / "@electric-sql" / "pglite").mkdir(parents=True)

        work_dir = database._prepare_pglite_work_dir(source, tmp_path / "runtime")

        linked = work_dir / "node_modules"
        assert linked.is_symlink(), "the module tree must be linked, not copied"
        assert (linked / "@electric-sql" / "pglite").is_dir(), (
            "the linked modules must resolve through to the primed tree"
        )

    def test_leaves_the_generated_script_to_py_pglite(self, tmp_path: Path) -> None:
        """The work directory must not inherit the seed's generated script.

        py-pglite bakes the socket path into ``pglite_manager.js`` and writes
        it only when absent, so copying the seed's copy would leave the server
        listening on the seed's socket and never becoming ready.
        """
        source = tmp_path / "npm-seed"
        (source / "node_modules").mkdir(parents=True)
        (source / "pglite_manager.js").write_text("seed socket\n", encoding="utf-8")
        (source / "package.json").write_text("{}\n", encoding="utf-8")

        work_dir = database._prepare_pglite_work_dir(source, tmp_path / "runtime")

        assert not (work_dir / "pglite_manager.js").exists(), (
            "the generated script must be written per work directory"
        )
        assert not (work_dir / "package.json").exists(), (
            "the manifest must be written per work directory"
        )

    def test_is_idempotent_for_a_prepared_directory(self, tmp_path: Path) -> None:
        """Reusing a prepared directory keeps working."""
        source = tmp_path / "npm-seed"
        (source / "node_modules").mkdir(parents=True)
        work_dir = tmp_path / "runtime"

        first = database._prepare_pglite_work_dir(source, work_dir)
        second = database._prepare_pglite_work_dir(source, work_dir)

        assert first == second, "the same directory must be returned"
        assert (second / "node_modules").is_symlink(), "the link must survive reuse"


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

    assert result.scalar_one() == 1, "exactly one public schema must survive resets"
    assert counting_lock.enter_count == 2, "both resets must acquire the schema lock"
    assert counting_lock.exit_count == 2, "both resets must release the schema lock"
    assert counting_lock.max_active_count == 1, "schema resets must not overlap"
