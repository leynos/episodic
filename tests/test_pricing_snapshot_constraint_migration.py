"""Upgrade coverage for deployed pricing snapshot unique constraints."""

import datetime as dt
import io
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from alembic.util import CommandError
from sqlalchemy.exc import IntegrityError

from alembic import command
from episodic.canonical.storage.alembic_helpers import alembic_config
from episodic.cost.storage import PricingSnapshotRecord

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
    from syrupy.assertion import SnapshotAssertion

_LEGACY_NAME = "pricing_snapshots_content_hash_key"
_CURRENT_NAME = "uq_pricing_snapshots_content_hash"
_PREVIOUS_REVISION = "20260624_000012"


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


async def _constraint(connection: AsyncConnection) -> tuple[str, str, int]:
    """Read the content-hash unique constraint and its backing index identity."""
    result = await connection.execute(
        sa.text(
            "SELECT conname, contype, conindid FROM pg_constraint "
            "WHERE conrelid = 'pricing_snapshots'::regclass AND contype = 'u'"
        )
    )
    name, kind, index_id = result.one()
    return str(name), str(kind), int(index_id)


async def _insert_snapshot(connection: AsyncConnection, snapshot_id: uuid.UUID) -> None:
    """Insert one deterministic snapshot with a shared content hash."""
    await connection.execute(
        sa.insert(PricingSnapshotRecord).values(
            id=snapshot_id,
            provider_name="openai",
            model="migration-test",
            operation="chat_completions",
            source_kind="provider_rate_card",
            currency="USD",
            billing_period_key="2026-06",
            rates_minor_per_metric={"input_tokens": 100},
            source_metadata={"source": "migration-test"},
            content_hash="migration-content-hash",
            retrieved_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        )
    )


async def _prepare_legacy_schema(connection: AsyncConnection) -> None:
    """Recreate the deployed schema at the previous migration head."""
    await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)
    # Before the repair, revision 000009 already carries the preview's name.
    if (await _constraint(connection))[0] == _CURRENT_NAME:
        await connection.execute(
            sa.text(
                "ALTER TABLE pricing_snapshots RENAME CONSTRAINT "
                "uq_pricing_snapshots_content_hash "
                "TO pricing_snapshots_content_hash_key"
            )
        )


async def _migration_target(
    connection: AsyncConnection,
    direction: typ.Literal["upgrade", "downgrade"],
) -> tuple[str, str]:
    """Prepare one migration direction and return its target and source name."""
    if direction == "upgrade":
        await _prepare_legacy_schema(connection)
        return "head", _LEGACY_NAME
    return _PREVIOUS_REVISION, _CURRENT_NAME


async def _assert_rejection_preserves_connection(
    connection: AsyncConnection,
    direction: typ.Literal["upgrade", "downgrade"],
    target_revision: str,
    message: str,
) -> None:
    """Verify failed validation leaves the caller's connection and revision intact."""
    revision_statement = sa.text("SELECT version_num FROM alembic_version")
    previous_revision = await connection.scalar(revision_statement)
    with pytest.raises(CommandError, match=message):
        async with connection.begin_nested():
            await connection.run_sync(_migrate, direction, target_revision)
    assert await connection.scalar(sa.text("SELECT 1")) == 1, (
        "migration rejection must leave the same database connection usable"
    )
    assert await connection.scalar(revision_statement) == previous_revision, (
        "migration rejection must not change the recorded Alembic revision"
    )


@pytest.mark.asyncio
async def test_fresh_schema_uses_named_pricing_snapshot_constraint(
    migrated_engine: AsyncEngine,
) -> None:
    """A fresh migration chain produces the constraint expected by storage."""
    async with migrated_engine.connect() as connection:
        name, kind, index_id = await _constraint(connection)
    assert name == _CURRENT_NAME, "fresh schemas must use the storage constraint name"
    assert kind == "u", "the content-hash constraint must enforce uniqueness"
    assert index_id > 0, "the unique constraint must retain a backing index"


@pytest.mark.asyncio
async def test_legacy_pricing_snapshot_constraint_upgrade_and_downgrade(
    migrated_engine: AsyncEngine,
) -> None:
    """Existing snapshots and uniqueness survive the rename in both directions."""
    async with migrated_engine.begin() as connection:
        await _prepare_legacy_schema(connection)
        legacy_constraint = await _constraint(connection)
        await _insert_snapshot(connection, uuid.UUID(int=1))

        await connection.run_sync(_migrate, "upgrade", "head")
        assert await _constraint(connection) == (
            _CURRENT_NAME,
            "u",
            legacy_constraint[2],
        ), "upgrade must rename the existing constraint without replacing its index"
        with pytest.raises(IntegrityError, match=_CURRENT_NAME):
            async with connection.begin_nested():
                await _insert_snapshot(connection, uuid.UUID(int=2))

        await connection.run_sync(_migrate, "downgrade", _PREVIOUS_REVISION)
        assert await _constraint(connection) == legacy_constraint, (
            "downgrade must restore the legacy name with the original unique index"
        )
        with pytest.raises(IntegrityError, match=_LEGACY_NAME):
            async with connection.begin_nested():
                await _insert_snapshot(connection, uuid.UUID(int=3))
        row_count = await connection.scalar(
            sa.select(sa.func.count()).select_from(PricingSnapshotRecord)
        )
        assert row_count == 1, "the persisted snapshot must survive both migrations"
        await connection.run_sync(_migrate, "upgrade", "head")
        assert await _constraint(connection) == (
            _CURRENT_NAME,
            "u",
            legacy_constraint[2],
        ), "re-upgrade must retain the same unique index"


@pytest.mark.asyncio
async def test_pricing_snapshot_constraint_migration_obeys_caller_rollback(
    migrated_engine: AsyncEngine,
) -> None:
    """Rolling back the caller's transaction also rolls back the schema rename."""
    async with migrated_engine.begin() as connection:
        await _prepare_legacy_schema(connection)
    async with migrated_engine.connect() as connection:
        transaction = await connection.begin()
        await connection.run_sync(_migrate, "upgrade", "head")
        assert (await _constraint(connection))[0] == _CURRENT_NAME, (
            "the caller's uncommitted upgrade must rename the constraint"
        )
        await transaction.rollback()
        assert (await _constraint(connection))[0] == _LEGACY_NAME, (
            "caller rollback must restore the legacy constraint name"
        )


@pytest.mark.asyncio
async def test_preview_pricing_snapshot_constraint_upgrade_is_noop(
    migrated_engine: AsyncEngine,
) -> None:
    """Previews initialized with the target name can still advance their revision."""
    async with migrated_engine.begin() as connection:
        await _prepare_legacy_schema(connection)
        await connection.execute(
            sa.text(
                "ALTER TABLE pricing_snapshots RENAME CONSTRAINT "
                "pricing_snapshots_content_hash_key "
                "TO uq_pricing_snapshots_content_hash"
            )
        )
        existing_constraint = await _constraint(connection)
        await connection.run_sync(_migrate, "upgrade", "head")
        assert await _constraint(connection) == existing_constraint, (
            "preview upgrade must preserve the existing named constraint and index"
        )
        revision = await connection.scalar(
            sa.text("SELECT version_num FROM alembic_version")
        )
        assert revision == "20261010_000013", (
            "preview upgrade must advance the Alembic revision despite the no-op rename"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
async def test_pricing_snapshot_constraint_migration_rejects_missing_uniqueness(
    migrated_engine: AsyncEngine,
    direction: typ.Literal["upgrade", "downgrade"],
) -> None:
    """An unexpected schema cannot advance without its unique constraint."""
    async with migrated_engine.begin() as connection:
        target_revision, source_name = await _migration_target(connection, direction)
        await connection.execute(
            sa.text(f"ALTER TABLE pricing_snapshots DROP CONSTRAINT {source_name}")
        )
        await _assert_rejection_preserves_connection(
            connection,
            direction,
            target_revision,
            "Pricing snapshot content-hash unique constraint is missing",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
@pytest.mark.parametrize("invalid_state", ["wrong-column", "wrong-type", "ambiguous"])
async def test_pricing_snapshot_constraint_migration_rejects_invalid_definition(
    migrated_engine: AsyncEngine,
    direction: typ.Literal["upgrade", "downgrade"],
    invalid_state: str,
) -> None:
    """Named constraints must uniquely protect exactly the content-hash column."""
    async with migrated_engine.begin() as connection:
        target_revision, source_name = await _migration_target(connection, direction)
        if invalid_state == "ambiguous":
            other_name = _CURRENT_NAME if direction == "upgrade" else _LEGACY_NAME
            ddl = (
                f"ALTER TABLE pricing_snapshots ADD CONSTRAINT {other_name} "
                "UNIQUE (content_hash)"
            )
            message = "constraints are ambiguous"
        else:
            await connection.execute(
                sa.text(f"ALTER TABLE pricing_snapshots DROP CONSTRAINT {source_name}")
            )
            definition = (
                "UNIQUE (model)"
                if invalid_state == "wrong-column"
                else "CHECK (content_hash <> '')"
            )
            ddl = (
                "ALTER TABLE pricing_snapshots ADD CONSTRAINT "
                f"{source_name} {definition}"
            )
            message = "constraint is malformed"
        await connection.execute(sa.text(ddl))
        await _assert_rejection_preserves_connection(
            connection,
            direction,
            target_revision,
            message,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
async def test_rejected_pricing_snapshot_migration_obeys_full_caller_rollback(
    migrated_engine: AsyncEngine,
    direction: typ.Literal["upgrade", "downgrade"],
) -> None:
    """Full rollback restores the dropped constraint and removes earlier writes."""
    async with migrated_engine.begin() as connection:
        target_revision, source_name = await _migration_target(connection, direction)
        original_constraint = await _constraint(connection)
    async with migrated_engine.connect() as connection:
        transaction = await connection.begin()
        await _insert_snapshot(connection, uuid.UUID(int=4))
        await connection.execute(
            sa.text(f"ALTER TABLE pricing_snapshots DROP CONSTRAINT {source_name}")
        )
        with pytest.raises(CommandError, match="unique constraint is missing"):
            await connection.run_sync(_migrate, direction, target_revision)
        await transaction.rollback()
        assert await _constraint(connection) == original_constraint, (
            "full caller rollback must restore the dropped constraint and its index"
        )
        assert (
            await connection.scalar(
                sa.select(sa.func.count()).select_from(PricingSnapshotRecord)
            )
            == 0
        ), "full caller rollback must remove writes made before migration rejection"


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_offline_pricing_snapshot_migration_keeps_schema_validation(
    direction: typ.Literal["upgrade", "downgrade"],
    snapshot: SnapshotAssertion,
) -> None:
    """Offline SQL retains definition checks, ambiguity rejection, and safe renaming."""
    config = alembic_config("postgresql://offline.example/episodic")
    output = io.StringIO()
    config.output_buffer = output
    migration = command.upgrade if direction == "upgrade" else command.downgrade
    revision = (
        f"{_PREVIOUS_REVISION}:head"
        if direction == "upgrade"
        else f"head:{_PREVIOUS_REVISION}"
    )
    migration(config, revision, sql=True)
    assert output.getvalue() == snapshot, (
        f"offline {direction} SQL must preserve schema validation, "
        "renaming, and revision"
    )
