"""Top-level rollback coverage for the content-address migration.

The other migration suites reject an upgrade inside a savepoint so that the
enclosing test transaction can still inspect the table. A deployed upgrade has
no such savepoint: Alembic owns the transaction and rolls back everything the
revision did. These tests commit the legacy seed first and then upgrade without
an enclosing transaction, which is the situation an operator meets.
"""

import hashlib
import typing as typ
import uuid

import pytest
from alembic.util import CommandError

from tests.fixtures.legacy_pricing_snapshots import (
    NEW_REVISION,
    assert_legacy_schema,
    collision_rows,
    migrate,
    rows,
    seed_legacy_rows,
)
from tests.fixtures.migration_doubles import colliding_sha256

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_SURVIVOR = uuid.UUID(int=101)
_DUPLICATE = uuid.UUID(int=102)


async def _seed_and_commit(engine: AsyncEngine) -> None:
    """Write the colliding legacy rows in a transaction of their own."""
    async with engine.begin() as connection:
        await seed_legacy_rows(connection, collision_rows(_SURVIVOR, _DUPLICATE))


async def _assert_legacy_rows_intact(engine: AsyncEngine) -> None:
    """Assert both seeded rows kept their legacy content and rates."""
    async with engine.connect() as connection:
        await assert_legacy_schema(connection)
        stored = {str(row["id"]): row for row in await rows(connection)}

    assert set(stored) == {str(_SURVIVOR), str(_DUPLICATE)}, (
        "a rejected top-level upgrade must keep both legacy rows"
    )
    assert {row["content_hash"] for row in stored.values()} == {
        "legacy-a",
        "legacy-b",
    }, "the partial rewrite must be rolled back, not committed"
    assert all(row["rates_minor_per_metric"] for row in stored.values()), (
        "the legacy rate column must survive the aborted upgrade"
    )


@pytest.mark.asyncio
async def test_upgrade_rejection_rolls_back_the_top_level_transaction(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A collision must abort the whole upgrade, not just a savepoint."""
    await _seed_and_commit(migrated_engine)
    monkeypatch.setattr(hashlib, "sha256", colliding_sha256)

    async with migrated_engine.connect() as connection:
        with pytest.raises(CommandError, match="content differs"):
            await connection.run_sync(migrate, "upgrade", NEW_REVISION)

    await _assert_legacy_rows_intact(migrated_engine)
