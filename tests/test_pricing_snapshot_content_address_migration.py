"""Online and offline coverage for the content-address migration."""

import datetime as dt
import io
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from alembic.util import CommandError

from alembic import command
from episodic.canonical.storage.alembic_helpers import alembic_config
from tests.fixtures.legacy_pricing_snapshots import LEGACY_REVISION, LEGACY_TABLE

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
    from syrupy.assertion import SnapshotAssertion


_NEW_REVISION = "20261110_000017"

_LEGACY_ROW = {
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


async def _seed_legacy_rows(
    connection: AsyncConnection,
    rows: cabc.Sequence[dict[str, object]],
) -> None:
    """Return the schema to the legacy revision and insert rows."""
    await connection.run_sync(_migrate, "downgrade", LEGACY_REVISION)
    await connection.execute(sa.insert(LEGACY_TABLE), list(rows))


async def _upgrade(connection: AsyncConnection) -> None:
    """Upgrade to the content-address revision."""
    await connection.run_sync(_migrate, "upgrade", _NEW_REVISION)


async def _columns(connection: AsyncConnection) -> set[str]:
    """Return the current columns of ``pricing_snapshots``."""
    result = await connection.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'pricing_snapshots'"
        )
    )
    return {str(row[0]) for row in result}


async def _rows(connection: AsyncConnection) -> list[dict[str, object]]:
    """Return every converted snapshot row keyed by column name."""
    result = await connection.execute(sa.text("SELECT * FROM pricing_snapshots"))
    return [dict(row._mapping) for row in result]


def _legacy_row(identifier: uuid.UUID, **overrides: object) -> dict[str, object]:
    """Build one legacy row with a fixed or overridden content shape."""
    return {**_LEGACY_ROW, "id": identifier, **overrides}


async def _recorded_revision(connection: AsyncConnection) -> str:
    """Return the Alembic revision the database records."""
    result = await connection.execute(
        sa.text("SELECT version_num FROM alembic_version")
    )
    return str(result.scalar_one())


async def _assert_legacy_schema(connection: AsyncConnection) -> None:
    """Assert a rejected upgrade left the legacy schema untouched."""
    columns = await _columns(connection)
    assert "billing_period_key" in columns, (
        "a rejected upgrade must leave the legacy columns"
    )
    assert "schema_version" not in columns, (
        "a rejected upgrade must not add the v1 columns"
    )
    assert await _recorded_revision(connection) == LEGACY_REVISION, (
        "a rejected upgrade must leave the recorded revision unchanged"
    )


async def _upgrade_is_rejected(connection: AsyncConnection, match: str) -> None:
    """Assert the upgrade fails inside a savepoint and changes nothing."""
    with pytest.raises(CommandError, match=match):
        async with connection.begin_nested():
            await _upgrade(connection)
    await _assert_legacy_schema(connection)


@pytest.mark.asyncio
async def test_upgrade_converts_legacy_rows(
    migrated_engine: AsyncEngine,
    snapshot: SnapshotAssertion,
) -> None:
    """Legacy rows become v1 rows with exact rates and a content hash."""
    async with migrated_engine.begin() as connection:
        await _seed_legacy_rows(
            connection,
            [_legacy_row(uuid.UUID(int=11))],
        )
        await _upgrade(connection)
        columns = await _columns(connection)
        rows = await _rows(connection)

    assert "billing_period_key" not in columns, (
        "the legacy billing period column must be dropped"
    )
    assert "rates_minor_per_metric" not in columns, (
        "the legacy integer rate column must be dropped"
    )
    assert {"schema_version", "service_kind", "rates", "recorded_at"} <= columns, (
        "the v1 columns must all be added"
    )
    assert len(rows) == 1, "the legacy row must survive the conversion"
    converted = rows[0]
    assert converted["schema_version"] == 1, "converted rows are schema version 1"
    assert converted["service_kind"] == "llm", "legacy rows convert as LLM pricing"
    assert converted["source_kind"] == "provider_rate_card", (
        "the legacy source kind must be preserved"
    )
    assert converted["rates"] == snapshot, (
        "legacy per-million rates must convert to exact lowest-term fractions"
    )
    assert converted["retrieved_at"] == dt.datetime(2026, 6, 1, tzinfo=dt.UTC), (
        "the retrieved instant must round-trip unchanged"
    )
    assert converted["effective_from"] == dt.datetime(2026, 6, 1, tzinfo=dt.UTC), (
        "the effective instant must round-trip unchanged"
    )
    assert str(converted["content_hash"]).startswith("sha256:"), (
        "the conversion must store a content hash"
    )
    assert converted["recorded_at"] is not None, (
        "the conversion must stamp a recording instant"
    )


@pytest.mark.asyncio
async def test_upgrade_rejects_a_recomputed_hash_collision(
    migrated_engine: AsyncEngine,
) -> None:
    """Two legacy rows with equal content cannot share one v1 identity."""
    first = uuid.UUID(int=21)
    second = uuid.UUID(int=22)
    # The legacy rows differ only in their stored hash, which keeps the seed
    # within the pre-existing uniqueness constraint; the conversion still
    # produces one shared identity.
    async with migrated_engine.begin() as connection:
        await _seed_legacy_rows(
            connection,
            [
                _legacy_row(first, content_hash="legacy-first"),
                _legacy_row(second, content_hash="legacy-second"),
            ],
        )
        await _upgrade_is_rejected(connection, str(first))


@pytest.mark.asyncio
async def test_upgrade_rejects_an_unknown_legacy_metric(
    migrated_engine: AsyncEngine,
) -> None:
    """A metric with no declared unit cannot be converted safely."""
    identifier = uuid.UUID(int=31)
    async with migrated_engine.begin() as connection:
        await _seed_legacy_rows(
            connection,
            [_legacy_row(identifier, rates_minor_per_metric={"mystery": 5})],
        )
        await _upgrade_is_rejected(connection, "mystery")


@pytest.mark.asyncio
async def test_upgrade_rejects_a_non_identifier_metadata_key(
    migrated_engine: AsyncEngine,
) -> None:
    """Canonical source metadata keys must be identifiers."""
    identifier = uuid.UUID(int=41)
    async with migrated_engine.begin() as connection:
        await _seed_legacy_rows(
            connection,
            [_legacy_row(identifier, source_metadata={"Source URL": "x"})],
        )
        await _upgrade_is_rejected(connection, str(identifier))


@pytest.mark.asyncio
async def test_downgrade_refuses_when_rows_exist(
    migrated_engine: AsyncEngine,
) -> None:
    """Converted rows cannot be mapped back to the legacy representation."""
    async with migrated_engine.begin() as connection:
        await _seed_legacy_rows(connection, [_legacy_row(uuid.UUID(int=51))])
        await _upgrade(connection)
        with pytest.raises(CommandError, match="empty"):
            await connection.run_sync(_migrate, "downgrade", LEGACY_REVISION)


def test_offline_upgrade_guards_against_existing_rows() -> None:
    """Offline DDL cannot convert rows, so it refuses to run on a populated table."""
    config = alembic_config("postgresql://offline.example/episodic")
    output = io.StringIO()
    config.output_buffer = output
    command.upgrade(config, f"{LEGACY_REVISION}:{_NEW_REVISION}", sql=True)

    emitted = output.getvalue()
    assert "DO $$" in emitted, "offline upgrade must emit a guard block"
    assert "pricing_snapshots" in emitted, "the guard must name the table it protects"
    assert "RAISE EXCEPTION" in emitted.upper(), (
        "the guard must raise on a populated table"
    )


def test_offline_downgrade_guards_against_existing_rows() -> None:
    """Offline downgrade emits the same emptiness guard."""
    config = alembic_config("postgresql://offline.example/episodic")
    output = io.StringIO()
    config.output_buffer = output
    command.downgrade(config, f"{_NEW_REVISION}:{LEGACY_REVISION}", sql=True)

    emitted = output.getvalue()
    assert "DO $$" in emitted, "offline downgrade must emit a guard block"
    assert "RAISE EXCEPTION" in emitted.upper(), (
        "the guard must raise on a populated table"
    )
