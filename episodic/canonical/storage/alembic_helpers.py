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

import os
import pathlib
import typing as typ

from alembic.config import Config

from alembic import command

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _escape_percent_signs(database_url: str) -> str:
    """Escape percent signs so ConfigParser stores the URL verbatim.

    Alembic keeps ``sqlalchemy.url`` in a ``ConfigParser`` that performs
    ``%`` interpolation, so percent-encoded credentials such as ``%40`` would
    otherwise raise on write. ``get_main_option`` reverses the escaping.

    Parameters
    ----------
    database_url : str
        Database connection URL, possibly containing percent-encoded
        credentials.

    Returns
    -------
    str
        The URL with each percent sign doubled.
    """
    return database_url.replace("%", "%%")


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
    cfg.set_main_option("sqlalchemy.url", _escape_percent_signs(database_url))
    return cfg


def configure_database_url(cfg: Config) -> None:
    """Ensure ``sqlalchemy.url`` is set on *cfg* from the environment or config.

    ``alembic/env.py`` delegates to this helper so the resolution rule can be
    exercised without importing the migration environment, which dispatches a
    migration run on import.

    Parameters
    ----------
    cfg : Config
        Alembic configuration mutated in place when ``DATABASE_URL`` is set.
        Percent characters are escaped for ConfigParser compatibility.

    Raises
    ------
    ValueError
        If ``DATABASE_URL`` is not set and ``sqlalchemy.url`` is empty.
    """
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        cfg.set_main_option("sqlalchemy.url", _escape_percent_signs(db_url))
        return
    if not cfg.get_main_option("sqlalchemy.url"):
        msg = "DATABASE_URL is not set and sqlalchemy.url is empty."
        raise ValueError(msg)


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
