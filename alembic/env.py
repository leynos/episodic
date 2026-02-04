"""Alembic environment for async SQLAlchemy migrations."""

from __future__ import annotations

import asyncio
import os
import typing as typ
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncConnection, async_engine_from_config

from alembic import context
from episodic.canonical.storage import Base

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection


def _configure_database_url() -> None:
    """Ensure sqlalchemy.url is set from the environment or existing config."""
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        config.set_main_option("sqlalchemy.url", db_url)
        return
    current = config.get_main_option("sqlalchemy.url")
    if not current:
        msg = "DATABASE_URL is not set and sqlalchemy.url is empty."
        raise RuntimeError(msg)


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
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
    """Run migrations in online mode."""
    connectable = config.attributes.get("connection")
    if connectable is not None:
        if isinstance(connectable, AsyncConnection):
            await connectable.run_sync(_do_run_migrations)
        else:
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
    """Entrypoint for online migrations."""
    connectable = config.attributes.get("connection")
    if connectable is not None:
        if isinstance(connectable, AsyncConnection):
            asyncio.run(connectable.run_sync(_do_run_migrations))
        else:
            _do_run_migrations(connectable)
        return
    asyncio.run(run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
