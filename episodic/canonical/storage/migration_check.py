"""Schema drift detection between ORM models and Alembic migrations.

This module compares the current SQLAlchemy model metadata against the
database state produced by applying all Alembic migrations. If they
diverge the check reports the differences and exits non-zero, allowing
CI to block pull requests with unmigrated model changes.

Examples
--------
Run the drift check from the command line:

>>> python -m episodic.canonical.storage.migration_check
"""

from __future__ import annotations

import asyncio
import sys
import typing as typ

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from episodic.canonical.storage.alembic_helpers import apply_migrations
from episodic.canonical.storage.models import Base
from episodic.logging import get_logger, log_error, log_info

if typ.TYPE_CHECKING:
    import sqlalchemy as sa
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine

_logger = get_logger(__name__)


def _compare_schema(
    connection: Connection,
    metadata: sa.MetaData,
) -> list[tuple[object, ...]]:
    """Compare a migrated database against ORM model metadata."""
    ctx = MigrationContext.configure(connection, opts={"compare_type": True})
    return typ.cast("list[tuple[object, ...]]", compare_metadata(ctx, metadata))


async def detect_schema_drift(
    engine: AsyncEngine,
) -> list[tuple[object, ...]]:
    """Detect differences between applied migrations and ORM models.

    Parameters
    ----------
    engine : AsyncEngine
        An async SQLAlchemy engine where all Alembic migrations have
        already been applied.

    Returns
    -------
    list[tuple[object, ...]]
        A list of differences. An empty list means the models and
        migrations are in sync.
    """
    async with engine.connect() as connection:
        return await connection.run_sync(_compare_schema, Base.metadata)


async def check_migrations_cli() -> int:
    """Run the schema drift check as a CLI entrypoint.

    Returns
    -------
    int
        Exit code: 0 when models and migrations match, 1 when drift is
        detected, 2 on infrastructure errors.
    """
    try:
        from py_pglite import PGliteConfig, PGliteManager
    except ModuleNotFoundError:
        log_error(
            _logger,
            "py-pglite is not installed; cannot run migration drift check.",
        )
        return 2

    import tempfile
    from pathlib import Path

    from sqlalchemy.ext.asyncio import create_async_engine

    with tempfile.TemporaryDirectory(prefix="episodic-migration-check-") as tmp:
        work_dir = Path(tmp)
        config = PGliteConfig(work_dir=work_dir)

        with PGliteManager(config):
            dsn = config.get_connection_string()
            engine = create_async_engine(dsn, pool_pre_ping=True)
            try:
                log_info(_logger, "Applying migrations to ephemeral database.")
                await apply_migrations(engine)

                log_info(_logger, "Checking for schema drift.")
                diffs = await detect_schema_drift(engine)
            finally:
                await engine.dispose()

    if diffs:
        log_error(
            _logger,
            "Schema drift detected (%s difference(s)):",
            len(diffs),
        )
        for diff in diffs:
            log_error(_logger, "  %s", diff)
        return 1

    log_info(_logger, "No schema drift detected.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(check_migrations_cli()))
