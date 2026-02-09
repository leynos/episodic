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
import pathlib
import sys
import typing as typ

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from alembic import command
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
    ctx = MigrationContext.configure(connection)
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


def _alembic_config(database_url: str) -> Config:
    """Create an Alembic configuration pointing at the project root."""
    root = pathlib.Path(__file__).resolve().parents[3]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    safe_url = database_url.replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", safe_url)
    return cfg


def _run_migrations(connection: Connection, cfg: Config) -> None:
    """Apply all Alembic migrations inside a sync context."""
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


async def _apply_migrations(engine: AsyncEngine) -> None:
    """Apply all Alembic migrations against *engine*."""
    cfg = _alembic_config(str(engine.url))
    async with engine.begin() as connection:
        await connection.run_sync(_run_migrations, cfg)


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

    from sqlalchemy.ext.asyncio import create_async_engine

    work_dir = pathlib.Path(tempfile.mkdtemp(prefix="episodic-migration-check-"))

    config = PGliteConfig(work_dir=work_dir)

    with PGliteManager(config):
        dsn = config.get_connection_string()
        engine = create_async_engine(dsn, pool_pre_ping=True)
        try:
            log_info(_logger, "Applying migrations to ephemeral database.")
            await _apply_migrations(engine)

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
