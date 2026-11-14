"""Schema coverage for downgrading the content-address migration.

The upgrade and its row conversion are covered by
``test_pricing_snapshot_content_address_migration.py``. This module proves the
reverse direction: an empty table downgrades to the legacy shape that released
``0.2.0`` writers expect, rather than to a half-restored schema.
"""

import typing as typ

import pytest

from tests.fixtures.legacy_pricing_snapshots import (
    LEGACY_REVISION,
    check_constraints,
    column_nullability,
    columns,
    downgrade,
    recorded_revision,
    upgrade,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_RESTORED_COLUMNS = ("billing_period_key", "rates_minor_per_metric")
_V1_COLUMNS = frozenset({
    "recorded_at",
    "source_document_content",
    "source_document_media_type",
    "rates",
    "service_kind",
    "schema_version",
})


@pytest.mark.asyncio
async def test_downgrade_restores_the_legacy_schema(
    migrated_engine: AsyncEngine,
) -> None:
    """An empty table downgrades to NOT NULL legacy columns and no v1 state."""
    async with migrated_engine.begin() as connection:
        await upgrade(connection)
        await downgrade(connection, LEGACY_REVISION)
        current = await columns(connection)
        nullability = await column_nullability(connection)
        constraints = await check_constraints(connection)
        revision = await recorded_revision(connection)

    assert set(_RESTORED_COLUMNS) <= current, (
        f"downgrade must restore the legacy columns, got {sorted(current)}"
    )
    assert {nullability[column] for column in _RESTORED_COLUMNS} == {"NO"}, (
        "the restored legacy columns are required for legacy writers, "
        f"got {[(column, nullability[column]) for column in _RESTORED_COLUMNS]}"
    )
    assert not _V1_COLUMNS & current, (
        "downgrade must drop every v1 column, still present: "
        f"{sorted(_V1_COLUMNS & current)}"
    )
    assert not constraints, (
        "downgrade must drop the v1 CHECK constraints, "
        f"still present: {sorted(constraints)}"
    )
    assert revision == LEGACY_REVISION, (
        f"downgrade must record the legacy revision, got {revision}"
    )
