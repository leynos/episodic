"""Granian runtime composition root for the Falcon ASGI service."""

from __future__ import annotations

import dataclasses as dc
import os
import typing as typ

import psycopg
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from episodic.canonical.storage import SqlAlchemyUnitOfWork

from . import create_app
from .dependencies import ApiDependencies, ReadinessProbe, ShutdownHook

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from falcon import asgi

    from episodic.canonical.ports import CanonicalUnitOfWork

    from .types import UowFactory


@dc.dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Runtime configuration required to boot the Falcon HTTP service."""

    database_url: str


_SUPPORTED_POSTGRES_DRIVERS = frozenset({"postgres", "postgresql"})
_SUPPORTED_ASYNC_POSTGRES_DRIVERS = frozenset({"asyncpg", "psycopg"})
_DEFAULT_ASYNC_POSTGRES_DRIVER = "psycopg"


def _load_runtime_config(
    environ: cabc.Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Read and validate runtime configuration from environment variables."""
    environment = os.environ if environ is None else environ
    database_url = environment.get("DATABASE_URL", "").strip()
    if not database_url:
        msg = "DATABASE_URL must be set before starting the HTTP service."
        raise RuntimeError(msg)
    return RuntimeConfig(database_url=database_url)


def _build_database_probe(
    database_url: str,
) -> tuple[ReadinessProbe, UowFactory, ShutdownHook]:
    """Build the database readiness probe and unit-of-work factory."""
    async_database_url, probe_database_url = _normalize_database_urls(database_url)
    engine = create_async_engine(async_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    async def check_database() -> bool:
        try:
            async with (
                await psycopg.AsyncConnection.connect(probe_database_url) as connection,
                connection.cursor() as cursor,
            ):
                await cursor.execute("SELECT 1")
                await cursor.fetchone()
        except psycopg.Error:
            return False
        return True

    def uow_factory() -> CanonicalUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return (
        ReadinessProbe(name="database", check=check_database),
        uow_factory,
        engine.dispose,
    )


def _normalize_database_urls(database_url: str) -> tuple[str, str]:
    """Build async-engine and sync-probe URLs from one operator-facing setting."""
    url = make_url(database_url)
    base_driver, separator, driver = url.drivername.partition("+")
    if base_driver not in _SUPPORTED_POSTGRES_DRIVERS:
        msg = (
            "DATABASE_URL must use PostgreSQL, for example "
            "postgresql://..., postgresql+asyncpg://..., or "
            "postgresql+psycopg://...."
        )
        raise RuntimeError(msg)

    if not separator:
        async_driver = _DEFAULT_ASYNC_POSTGRES_DRIVER
    elif driver in _SUPPORTED_ASYNC_POSTGRES_DRIVERS:
        async_driver = driver
    else:
        msg = (
            "DATABASE_URL async drivers must be one of asyncpg or psycopg "
            f"(got {url.drivername!r})."
        )
        raise RuntimeError(msg)

    normalized_driver = "postgresql"
    async_database_url = url.set(
        drivername=f"{normalized_driver}+{async_driver}"
    ).render_as_string(hide_password=False)
    probe_database_url = url.set(drivername=normalized_driver).render_as_string(
        hide_password=False
    )
    return async_database_url, probe_database_url


def create_app_from_env() -> asgi.App:
    """Build the Falcon ASGI service from environment configuration."""
    config = _load_runtime_config()
    database_probe, uow_factory, shutdown_hook = _build_database_probe(
        config.database_url
    )
    return create_app(
        ApiDependencies(
            uow_factory=uow_factory,
            readiness_probes=(database_probe,),
            shutdown_hooks=(shutdown_hook,),
        )
    )
