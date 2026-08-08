"""Alembic environment for async SQLAlchemy migrations.

This module configures Alembic for async SQLAlchemy engines and supports both
offline and online migration execution.

Examples
--------
Run migrations with Alembic:

>>> alembic upgrade head
"""

import asyncio
import typing as typ
from logging.config import fileConfig

from alembic.context import config
from sqlalchemy import MetaData, pool
from sqlalchemy.ext.asyncio import AsyncConnection, async_engine_from_config

from alembic import context
from episodic.canonical.storage import Base
from episodic.canonical.storage.alembic_helpers import configure_database_url

if config.config_file_name:
    fileConfig(config.config_file_name)


def _migration_metadata() -> MetaData:
    """Return the canonical SQLAlchemy metadata used by migrations."""
    return Base.metadata


target_metadata = _migration_metadata()

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection


def _configure_database_url() -> None:
    """Ensure sqlalchemy.url is set from the environment or existing config."""
    configure_database_url(config)


def run_migrations_offline() -> None:
    """Run migrations in offline mode.

    Raises
    ------
    ValueError
        If ``DATABASE_URL`` is not set and ``sqlalchemy.url`` is empty.
    """  # noqa: DOC502  # Documents an exception propagated by configuration.
    _configure_database_url()
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    """Configure the context and run migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    """Run migrations in online mode.

    Raises
    ------
    ValueError
        If ``DATABASE_URL`` is not set and ``sqlalchemy.url`` is empty.
    """  # noqa: DOC502  # Documents an exception propagated by configuration.
    connectable = config.attributes.get("connection")
    match connectable:
        case AsyncConnection():
            await connectable.run_sync(_do_run_migrations)
            return
        case None:
            pass
        case _:
            _do_run_migrations(connectable)
            return

    _configure_database_url()
    section = config.get_section(config.config_ini_section) or {}
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entrypoint for online migrations.

    Raises
    ------
    ValueError
        If ``DATABASE_URL`` is not set and ``sqlalchemy.url`` is empty.
    """  # noqa: DOC502  # Documents an exception propagated by configuration.
    connectable = config.attributes.get("connection")
    match connectable:
        case AsyncConnection():
            asyncio.run(connectable.run_sync(_do_run_migrations))
            return
        case None:
            pass
        case _:
            _do_run_migrations(connectable)
            return
    asyncio.run(run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
