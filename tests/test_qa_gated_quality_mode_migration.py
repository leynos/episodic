"""Migration coverage for the QA-gated quality labels (INV-11).

The PostgreSQL labels must match the Python enums, a ``qa_gated`` row must be
insertable after the upgrade transaction commits, and a downgrade must refuse
to run while such rows exist. Alembic's ``compare_metadata`` ignores enum
labels, so this test reads ``pg_enum`` directly.
"""

import dataclasses as dc
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from alembic.util import CommandError

from alembic import command
from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.alembic_helpers import alembic_config
from tests.canonical_storage._generation_run_support import (
    NOW,
    GenerationRunFixture,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import (
        AsyncConnection,
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
    )

_PREVIOUS_REVISION = "20261110_000017"
_HEAD_REVISION = "20261123_000019"


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


async def _labels(connection: AsyncConnection, enum_name: str) -> tuple[str, ...]:
    """Read an enum's labels in declaration order from ``pg_enum``."""
    result = await connection.execute(
        sa.text(
            "SELECT e.enumlabel FROM pg_enum AS e "
            "JOIN pg_type AS t ON t.oid = e.enumtypid "
            "WHERE t.typname = :name ORDER BY e.enumsortorder"
        ),
        {"name": enum_name},
    )
    return tuple(str(row[0]) for row in result)


async def _assert_label_parity(connection: AsyncConnection) -> None:
    """Assert both enum types equal their Python enum value sets."""
    assert set(await _labels(connection, "quality_mode")) == {
        mode.value for mode in QualityMode
    }, "quality_mode labels must equal the Python enum values"
    assert set(await _labels(connection, "qa_status")) == {
        status.value for status in QaStatus
    }, "qa_status labels must equal the Python enum values"


@pytest.mark.asyncio
async def test_previous_revision_lacks_the_qa_gated_labels(
    migrated_engine: AsyncEngine,
) -> None:
    """At the previous head, the parity check must report missing labels."""
    async with migrated_engine.begin() as connection:
        await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)
    async with migrated_engine.connect() as connection:
        assert set(await _labels(connection, "quality_mode")) == {
            QualityMode.DRAFT_WITHOUT_QA.value
        }, "the previous revision has one quality-mode label"
        assert set(await _labels(connection, "qa_status")) == {
            QaStatus.SKIPPED.value
        }, "the previous revision has one QA-status label"
        with pytest.raises(AssertionError, match="quality_mode labels"):
            await _assert_label_parity(connection)


@pytest.mark.asyncio
async def test_upgrade_adds_labels_and_accepts_qa_gated_rows(
    migrated_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Labels match the enums, and a qa_gated row survives a committed upgrade."""
    async with migrated_engine.begin() as connection:
        await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)
    # A separate transaction commits the ADD VALUE before any row uses it.
    async with migrated_engine.begin() as connection:
        await connection.run_sync(_migrate, "upgrade", _HEAD_REVISION)
    async with migrated_engine.connect() as connection:
        await _assert_label_parity(connection)

    run = dc.replace(
        make_generation_run(GenerationRunFixture(run_id=uuid.uuid7())),
        quality_mode=QualityMode.QA_GATED,
        qa_status=QaStatus.PENDING,
        skip_qa_rationale=None,
    )
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.generation_runs.create_run(run)
        await uow.commit()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        reloaded = await uow.generation_runs.get_run(stored.id)
    assert reloaded is not None, "the qa_gated row must be readable"
    assert reloaded.quality_mode is QualityMode.QA_GATED, (
        f"persisted quality_mode={reloaded.quality_mode!r}"
    )
    assert reloaded.qa_status is QaStatus.PENDING, (
        f"persisted qa_status={reloaded.qa_status!r}"
    )


@pytest.mark.asyncio
async def test_downgrade_refuses_while_new_labels_are_in_use(
    migrated_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A lossy downgrade is refused, and the schema stays intact."""
    run = dc.replace(
        make_generation_run(GenerationRunFixture(run_id=uuid.uuid7())),
        status=GenerationRunStatus.FAILED,
        ended_at=NOW,
        quality_mode=QualityMode.QA_GATED,
        qa_status=QaStatus.FAILED,
        skip_qa_rationale=None,
    )
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async with migrated_engine.connect() as connection:
        revision_statement = sa.text("SELECT version_num FROM alembic_version")
        with pytest.raises(CommandError, match="Cannot downgrade"):
            async with connection.begin_nested():
                await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)
        assert await connection.scalar(revision_statement) == _HEAD_REVISION, (
            "a refused downgrade must not move the Alembic revision"
        )
    async with migrated_engine.connect() as connection:
        await _assert_label_parity(connection)


@pytest.mark.asyncio
async def test_downgrade_recreates_original_types_when_no_rows_use_new_labels(
    migrated_engine: AsyncEngine,
) -> None:
    """An unused upgrade downgrades cleanly and can be re-applied."""
    async with migrated_engine.begin() as connection:
        await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)
    async with migrated_engine.begin() as connection:
        await connection.run_sync(_migrate, "upgrade", "head")
    async with migrated_engine.begin() as connection:
        await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)
    async with migrated_engine.connect() as connection:
        assert set(await _labels(connection, "quality_mode")) == {
            QualityMode.DRAFT_WITHOUT_QA.value
        }, "downgrade must restore the single quality-mode label"
        assert set(await _labels(connection, "qa_status")) == {
            QaStatus.SKIPPED.value
        }, "downgrade must restore the single QA-status label"
    async with migrated_engine.begin() as connection:
        await connection.run_sync(_migrate, "upgrade", "head")
    async with migrated_engine.connect() as connection:
        await _assert_label_parity(connection)
