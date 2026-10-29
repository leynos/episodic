"""Reversibility coverage for the review-checkpoint migration (INV-MIG-2).

``downgrade()`` is rarely exercised, and native enums are the usual thing left
behind: dropping a table does not drop the enum types it used. This module pins
both halves of the round trip, so a revision that forgets either explicit
``.drop(bind, checkfirst=True)`` call fails here rather than in a production
rollback.
"""

import itertools
import typing as typ

import pytest
import sqlalchemy as sa

from alembic import command
from episodic.canonical.storage.alembic_helpers import alembic_config

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

#: The revision the review-checkpoint migration chains off. The migration
#: itself is reached through ``"head"`` rather than by name, so this module
#: does not pin a date the revision counter already identifies.
_PREVIOUS_REVISION = "20261010_000013"

#: Both enum types the revision owns, and must therefore remove on downgrade.
_CHECKPOINT_ENUMS = ("review_checkpoint_status", "review_checkpoint_action")


def _migrate(
    connection: Connection,
    direction: typ.Literal["upgrade", "downgrade"],
    revision: str,
) -> None:
    """Run Alembic on the caller's existing transaction."""
    config = alembic_config(str(connection.engine.url))
    config.attributes["connection"] = connection
    migration = command.upgrade if direction == "upgrade" else command.downgrade
    migration(config, revision)


async def _table_names(connection: AsyncConnection) -> set[str]:
    """Return the tables present in the current schema."""
    statement = sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    result = await connection.execute(statement)
    return set(itertools.starmap(str, result))


async def _enum_types(connection: AsyncConnection) -> set[str]:
    """Return the enum type names left in the catalogue."""
    statement = sa.text("SELECT typname FROM pg_type WHERE typname = ANY(:names)")
    result = await connection.execute(statement, {"names": list(_CHECKPOINT_ENUMS)})
    return set(itertools.starmap(str, result))


async def _schema_fingerprint(connection: AsyncConnection) -> set[tuple[str, str]]:
    """Return every column of every review-checkpoint table, by name and type."""
    statement = sa.text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'review_checkpoints' "
        "ORDER BY ordinal_position"
    )
    result = await connection.execute(statement)
    return {(str(column), str(kind)) for column, kind in result}


@pytest.mark.asyncio
async def test_review_checkpoint_migration_creates_table_and_enums(
    migrated_engine: AsyncEngine,
) -> None:
    """The head revision creates the table and both enum types."""
    async with migrated_engine.connect() as connection:
        assert "review_checkpoints" in await _table_names(connection), (
            "the migration must create the review_checkpoints table"
        )
        assert await _enum_types(connection) == set(_CHECKPOINT_ENUMS), (
            "the migration must create both review-checkpoint enum types"
        )


@pytest.mark.asyncio
async def test_downgrade_removes_table_and_both_enums(
    migrated_engine: AsyncEngine,
) -> None:
    """Downgrading one revision drops the table and orphans no enum type."""
    async with migrated_engine.begin() as connection:
        await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)

        assert "review_checkpoints" not in await _table_names(connection), (
            "downgrade must drop the review_checkpoints table"
        )
        assert await _enum_types(connection) == set(), (
            "downgrade must drop both enum types; dropping the table does not"
        )


@pytest.mark.asyncio
async def test_upgrade_downgrade_upgrade_leaves_schema_identical(
    migrated_engine: AsyncEngine,
) -> None:
    """A downgrade/upgrade round trip restores the schema exactly."""
    async with migrated_engine.begin() as connection:
        at_head = await _schema_fingerprint(connection)

        await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)
        await connection.run_sync(_migrate, "upgrade", "head")

        assert await _schema_fingerprint(connection) == at_head, (
            "the round trip must leave the schema identical to a single upgrade"
        )
        assert await _enum_types(connection) == set(_CHECKPOINT_ENUMS), (
            "the re-upgrade must recreate both enum types"
        )


@pytest.mark.asyncio
async def test_review_checkpoints_keeps_its_check_constraints(
    migrated_engine: AsyncEngine,
) -> None:
    """Both CHECK constraints survive the round trip, not just the columns."""
    async with migrated_engine.begin() as connection:
        at_head = await connection.scalar(
            sa.text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid = 'review_checkpoints'::regclass AND contype = 'c'"
            )
        )
        await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)
        await connection.run_sync(_migrate, "upgrade", "head")
        after = await connection.scalar(
            sa.text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid = 'review_checkpoints'::regclass AND contype = 'c'"
            )
        )

    assert at_head == 2, "the table must carry both CHECK constraints"
    assert after == at_head, "the round trip must restore both CHECK constraints"
