"""Shared Alembic configuration and migration helpers.

This module provides reusable functions for configuring Alembic and applying
migrations against an async SQLAlchemy engine. Both the schema drift detection
module and the test fixtures import from here to avoid duplicating the
configuration and migration-application logic.

Examples
--------
Apply all migrations to an async engine:

>>> await apply_migrations(engine)
"""

import pathlib
import typing as typ

from alembic.config import Config

from alembic import command

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]


def alembic_config(database_url: str) -> Config:
    """Create an Alembic configuration pointing at the project root.

    Parameters
    ----------
    database_url : str
        Database connection URL. Percent characters are escaped for
        ConfigParser compatibility.

    Returns
    -------
    Config
        A configured Alembic ``Config`` instance.
    """
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    safe_url = database_url.replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", safe_url)
    return cfg


def _run_migrations(connection: Connection, cfg: Config) -> None:
    """Apply all Alembic migrations inside a sync context."""
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


async def apply_migrations(engine: AsyncEngine) -> None:
    """Apply all Alembic migrations against *engine*.

    Parameters
    ----------
    engine : AsyncEngine
        An async SQLAlchemy engine to migrate.
    """
    cfg = alembic_config(str(engine.url))
    async with engine.begin() as connection:
        await connection.run_sync(_run_migrations, cfg)
