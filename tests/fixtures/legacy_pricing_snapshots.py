"""The deployed pricing-snapshot schema shared by the migration suites.

The pricing migration suites seed and inspect the pre-content-address table and
upgrade it. Keeping the table definition, the revision pair, and the migration
helpers here means a schema or Alembic change is made once, rather than in
several copies that could drift apart silently.
"""

import datetime as dt
import typing as typ

import pytest
import sqlalchemy as sa
from alembic.util import CommandError
from sqlalchemy.dialects import postgresql

from alembic import command
from episodic.canonical.storage.alembic_helpers import alembic_config

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

#: The revision immediately before the content-address migration.
LEGACY_REVISION = "20261031_000016"

#: The content-address migration under test.
NEW_REVISION = "20261110_000017"

LEGACY_TABLE = sa.table(
    "pricing_snapshots",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("provider_name", sa.Text),
    sa.column("model", sa.Text),
    sa.column("operation", sa.Text),
    sa.column("source_kind", sa.Text),
    sa.column("currency", sa.String(3)),
    sa.column("billing_period_key", sa.Text),
    sa.column("rates_minor_per_metric", postgresql.JSONB),
    sa.column("source_metadata", postgresql.JSONB),
    sa.column("content_hash", sa.Text),
    sa.column("retrieved_at", sa.DateTime(timezone=True)),
    sa.column("effective_from", sa.DateTime(timezone=True)),
)

#: One representative legacy row before any per-test overrides.
DEFAULT_LEGACY_ROW: dict[str, object] = {
    "provider_name": "openai",
    "model": "gpt-4o-mini",
    "operation": "chat_completions",
    "source_kind": "provider_rate_card",
    "currency": "USD",
    "billing_period_key": "2026-06",
    "rates_minor_per_metric": {"input_tokens": 100, "output_tokens": 200},
    "source_metadata": {"source": "migration-test"},
    "content_hash": "legacy-raw-bytes-hash",
    "retrieved_at": dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
    "effective_from": dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
}


def legacy_row(identifier: uuid.UUID, **overrides: object) -> dict[str, object]:
    """Build one legacy row with a fixed or overridden content shape."""
    return {**DEFAULT_LEGACY_ROW, "id": identifier, **overrides}


def collision_rows(
    survivor: uuid.UUID,
    duplicate: uuid.UUID,
) -> list[dict[str, object]]:
    """Build two legacy rows whose canonical documents differ."""
    return [
        legacy_row(survivor, provider_name="openai", content_hash="legacy-a"),
        legacy_row(duplicate, provider_name="anthropic", content_hash="legacy-b"),
    ]


def migrate(
    connection: Connection,
    direction: typ.Literal["upgrade", "downgrade"],
    revision: str,
) -> None:
    """Run Alembic on the caller's existing transaction."""
    config = alembic_config(str(connection.engine.url))
    config.attributes["connection"] = connection
    migration = command.upgrade if direction == "upgrade" else command.downgrade
    migration(config, revision)


async def seed_legacy_rows(
    connection: AsyncConnection,
    rows: cabc.Sequence[dict[str, object]],
) -> None:
    """Return the schema to the legacy revision and insert rows."""
    await connection.run_sync(migrate, "downgrade", LEGACY_REVISION)
    await connection.execute(sa.insert(LEGACY_TABLE), list(rows))


async def upgrade(connection: AsyncConnection) -> None:
    """Upgrade to the content-address revision."""
    await connection.run_sync(migrate, "upgrade", NEW_REVISION)


async def downgrade(connection: AsyncConnection, revision: str) -> None:
    """Downgrade to *revision* through the caller's transaction."""
    await connection.run_sync(migrate, "downgrade", revision)


async def columns(connection: AsyncConnection) -> set[str]:
    """Return the current columns of ``pricing_snapshots``."""
    result = await connection.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'pricing_snapshots'"
        )
    )
    return {str(row[0]) for row in result}


async def rows(connection: AsyncConnection) -> list[dict[str, object]]:
    """Return every converted snapshot row keyed by column name."""
    result = await connection.execute(sa.text("SELECT * FROM pricing_snapshots"))
    return [dict(row._mapping) for row in result]


async def recorded_revision(connection: AsyncConnection) -> str:
    """Return the Alembic revision the database records."""
    result = await connection.execute(
        sa.text("SELECT version_num FROM alembic_version")
    )
    return str(result.scalar_one())


async def assert_legacy_schema(connection: AsyncConnection) -> None:
    """Assert a rejected upgrade left the legacy schema untouched."""
    current = await columns(connection)
    assert "billing_period_key" in current, (
        "a rejected upgrade must leave the legacy columns"
    )
    assert "schema_version" not in current, (
        "a rejected upgrade must not add the v1 columns"
    )
    assert await recorded_revision(connection) == LEGACY_REVISION, (
        "a rejected upgrade must leave the recorded revision unchanged"
    )


async def upgrade_is_rejected(connection: AsyncConnection, match: str) -> None:
    """Assert the upgrade fails inside a savepoint and changes nothing."""
    with pytest.raises(CommandError, match=match):
        async with connection.begin_nested():
            await upgrade(connection)
    await assert_legacy_schema(connection)


async def assert_upgrade_fails(
    migrated_engine: AsyncEngine,
    identifier: uuid.UUID,
    overrides: cabc.Mapping[str, object],
    match: str,
) -> None:
    """Seed one overridden legacy row and assert the upgrade rejects it."""
    async with migrated_engine.begin() as connection:
        await seed_legacy_rows(connection, [legacy_row(identifier, **overrides)])
        await upgrade_is_rejected(connection, match)
