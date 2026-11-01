"""The migrated expired-lease index still matches the declaration storage uses.

Alembic's autogenerate does not compare partial-index predicates, so
``make check-migrations`` reports no drift however far the deployed index and
``GenerationRunRecord.__table_args__`` diverge. This test reads the index back
out of PostgreSQL and compares it with the one constant both sites import.
"""

import re
import typing as typ

import pytest
import sqlalchemy as sa

from episodic.canonical.storage.generation_run_schema import (
    GENERATION_RUN_EXPIRED_LEASE_INDEX,
    GENERATION_RUN_EXPIRED_LEASE_PREDICATE_SQL,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


def _normalise(sql: str) -> str:
    """Strip the formatting PostgreSQL adds, keeping comparable tokens.

    The server rewrites ``status = 'running'`` as
    ``((status)::text = 'running'::text)``, so the declared predicate only
    matches the deployed one once casts, parentheses, and whitespace go.

    Returns
    -------
    str
        The input with casts, parentheses, and whitespace removed.
    """
    return re.sub(r"[\s()]", "", sql.replace("::text", ""))


async def _index_definition(connection: AsyncConnection) -> str:
    """Return the deployed definition of the expired-lease index."""
    statement = sa.text(
        "SELECT indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' AND tablename = 'generation_runs' "
        "AND indexname = :name"
    )
    definition = await connection.scalar(
        statement, {"name": GENERATION_RUN_EXPIRED_LEASE_INDEX}
    )
    assert definition is not None, "the expired-lease index must exist after migration"
    return str(definition)


@pytest.mark.asyncio
async def test_expired_lease_index_matches_its_declared_predicate(
    migrated_engine: AsyncEngine,
) -> None:
    """The migrated index is partial on the declared lease-holder predicate."""
    async with migrated_engine.connect() as connection:
        definition = await _index_definition(connection)

    assert "lease_expires_at" in definition, definition
    assert "WHERE" in definition, f"the index must stay partial: {definition}"
    assert _normalise(GENERATION_RUN_EXPIRED_LEASE_PREDICATE_SQL) in _normalise(
        definition
    ), f"the deployed predicate drifted from the declaration: {definition}"
