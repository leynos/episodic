"""Granian runtime composition root for the Falcon ASGI service."""

from __future__ import annotations

import dataclasses as dc
import os
import typing as typ

import psycopg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from episodic.canonical.storage import SqlAlchemyUnitOfWork

from . import create_app
from .dependencies import ApiDependencies, ReadinessProbe

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from falcon import asgi

    from episodic.canonical.ports import CanonicalUnitOfWork

    from .types import UowFactory


@dc.dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Runtime configuration required to boot the Falcon HTTP service."""

    database_url: str


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
) -> tuple[ReadinessProbe, UowFactory]:
    """Build the database readiness probe and unit-of-work factory."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )
    probe_database_url = database_url.replace("+asyncpg", "").replace("+psycopg", "")

    async def check_database() -> bool:
        try:
            connection = await psycopg.AsyncConnection.connect(probe_database_url)
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    await cursor.fetchone()
            finally:
                await connection.close()
        except psycopg.Error:
            return False
        return True

    def uow_factory() -> CanonicalUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return ReadinessProbe(name="database", check=check_database), uow_factory


def create_app_from_env() -> asgi.App:
    """Build the Falcon ASGI service from environment configuration."""
    config = _load_runtime_config()
    database_probe, uow_factory = _build_database_probe(config.database_url)
    return create_app(
        ApiDependencies(
            uow_factory=uow_factory,
            readiness_probes=(database_probe,),
        )
    )
