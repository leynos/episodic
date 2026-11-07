"""Downgrade and re-upgrade coverage for the QA artefact migration.

The migration must reverse cleanly, dropping its tables before the enum types
they depend on, and then recreate a schema that still records and reads an
evaluation.
"""

import typing as typ

import pytest
import sqlalchemy as sa

from alembic import command
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.alembic_helpers import alembic_config
from tests.canonical_storage._qa_artefact_support import (
    create_episode,
    make_evaluation,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import (
        AsyncConnection,
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
    )

    type SessionFactory = async_sessionmaker[AsyncSession]
else:
    type SessionFactory = object

_QA_REVISION = "20261031_000016"
_PREVIOUS_REVISION = "20261020_000015"
_TABLES = ("qa_evaluations", "qa_findings")
_ENUMS = ("qa_evaluator", "qa_compliance_status", "qa_finding_severity")


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


async def _recorded_revision(connection: AsyncConnection) -> str | None:
    """Return the revision Alembic has recorded."""
    return await connection.scalar(sa.text("SELECT version_num FROM alembic_version"))


async def _relation_exists(connection: AsyncConnection, name: str) -> bool:
    """Return whether the named relation exists in the current schema."""
    statement = sa.text("SELECT to_regclass(:name) IS NOT NULL")
    return bool(await connection.scalar(statement, {"name": name}))


async def _enum_exists(connection: AsyncConnection, name: str) -> bool:
    """Return whether the named PostgreSQL enum type exists."""
    statement = sa.text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = :name)")
    return bool(await connection.scalar(statement, {"name": name}))


async def _assert_schema_state(
    connection: AsyncConnection,
    *,
    present: bool,
) -> None:
    """Assert every QA table and enum is present or absent as requested."""
    for table in _TABLES:
        assert await _relation_exists(connection, table) is present, table
    for enum_name in _ENUMS:
        assert await _enum_exists(connection, enum_name) is present, enum_name


@pytest.mark.asyncio
async def test_qa_migration_round_trips_through_its_downgrade(
    migrated_engine: AsyncEngine,
    session_factory: SessionFactory,
) -> None:
    """Downgrading removes the artefacts and upgrading restores a usable schema."""
    async with migrated_engine.begin() as connection:
        assert await _recorded_revision(connection) == _QA_REVISION, (
            "the migrated database should record the QA revision"
        )
        await _assert_schema_state(connection, present=True)

        await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)

        assert await _recorded_revision(connection) == _PREVIOUS_REVISION, (
            "the downgrade should record the previous revision"
        )
        await _assert_schema_state(connection, present=False)

    async with migrated_engine.begin() as connection:
        await connection.run_sync(_migrate, "upgrade", _QA_REVISION)

        assert await _recorded_revision(connection) == _QA_REVISION, (
            "the re-upgrade should record the QA revision again"
        )
        await _assert_schema_state(connection, present=True)

    episode_id = await create_episode(session_factory)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.qa_artefacts.record_evaluation(
            make_evaluation(episode_id, idempotency_key="after-downgrade")
        )
        await uow.commit()
        reloaded = await uow.qa_artefacts.get_evaluation(stored.summary_record.id)

    assert reloaded is not None, "the re-upgraded schema should accept a recording"
    assert reloaded.summary_record.id == stored.summary_record.id, (
        "the reloaded evaluation should keep the identifier it was stored under"
    )
