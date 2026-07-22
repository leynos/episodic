"""Granian runtime composition root for the Falcon ASGI service."""

import dataclasses as dc
import os
import pathlib
import typing as typ

import psycopg
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from episodic.canonical.storage import FilesystemObjectStore, SqlAlchemyUnitOfWork
from episodic.cost.engine import PricingEngine
from episodic.cost.pricing_catalogue import FilePricingCatalogue
from episodic.cost.recorder import CostRecorder
from episodic.generation import (
    InProcessGenerationRunLauncher,
    LLMDraftScriptGenerator,
    LLMDraftScriptGeneratorConfig,
)
from episodic.llm import LLMProviderOperation
from episodic.logging import get_logger, log_info, log_warning

from . import create_app
from .dependencies import ApiDependencies, ReadinessProbe, ShutdownHook

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from falcon import asgi

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.llm import LLMPort

    from .types import UowFactory


@dc.dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Runtime configuration required to boot the Falcon HTTP service."""

    database_url: str
    source_intake_object_store_root: pathlib.Path


_SUPPORTED_POSTGRES_DRIVERS = frozenset({"postgres", "postgresql"})
_SUPPORTED_ASYNC_POSTGRES_DRIVERS = frozenset({"asyncpg", "psycopg"})
_DEFAULT_ASYNC_POSTGRES_DRIVER = "psycopg"
GRANIAN_FACTORY_TARGET = "episodic.api.runtime:create_app_from_env"
GRANIAN_INTERFACE = "asgi"
HTTP_BIND_PORT = 8080
_DEFAULT_DRAFT_MODEL = "gpt-4o-mini"
_DEFAULT_LLM_PROVIDER_NAME = "openai"
_DEFAULT_PRICING_DIRECTORY = pathlib.Path("config/pricing-snapshots")


class PsycopgConnectKwargs(typ.TypedDict, total=False):
    """Connection kwargs accepted by the database readiness probe."""

    host: str
    port: int
    dbname: str
    user: str
    password: str
    sslmode: str


logger = get_logger(__name__)


def _load_runtime_config(
    environ: cabc.Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Read and validate runtime configuration from environment variables."""
    environment = os.environ if environ is None else environ
    database_url = environment.get("DATABASE_URL", "").strip()
    if not database_url:
        msg = "DATABASE_URL must be set before starting the HTTP service."
        raise RuntimeError(msg)
    object_store_root = environment.get("SOURCE_INTAKE_OBJECT_STORE_ROOT", "").strip()
    if not object_store_root:
        log_warning(
            logger,
            "runtime_config_missing setting=%s",
            "SOURCE_INTAKE_OBJECT_STORE_ROOT",
        )
        msg = (
            "SOURCE_INTAKE_OBJECT_STORE_ROOT must be set before starting "
            "the HTTP service."
        )
        raise RuntimeError(msg)
    log_info(
        logger,
        "runtime_config_loaded source_intake_object_store_configured",
    )
    return RuntimeConfig(
        database_url=database_url,
        source_intake_object_store_root=pathlib.Path(object_store_root),
    )


def _build_database_probe(
    database_url: str,
) -> tuple[ReadinessProbe, UowFactory, ShutdownHook]:
    """Build the database readiness probe and unit-of-work factory."""
    async_database_url, probe_connection_kwargs = _normalize_database_urls(database_url)
    engine = create_async_engine(async_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    async def check_database() -> bool:
        try:
            async with (
                await psycopg.AsyncConnection.connect(
                    **probe_connection_kwargs
                ) as connection,
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


def _build_generation_launcher(
    uow_factory: UowFactory,
    llm_port: LLMPort | None,
    *,
    object_store: ObjectStorePort | None = None,
    draft_model: str = _DEFAULT_DRAFT_MODEL,
) -> InProcessGenerationRunLauncher | None:
    """Build the no-QA generation-run launcher when an LLM port is configured."""
    if llm_port is None:
        return None
    pricing_catalogue = FilePricingCatalogue(_DEFAULT_PRICING_DIRECTORY)

    def _cost_recorder(uow: CanonicalUnitOfWork) -> CostRecorder:
        return CostRecorder(
            ledger=uow.cost_ledger,
            pricing_catalogue=pricing_catalogue,
            pricing_engine=PricingEngine(),
        )

    return InProcessGenerationRunLauncher(
        uow_factory=uow_factory,
        draft_generator=LLMDraftScriptGenerator(
            llm=llm_port,
            config=LLMDraftScriptGeneratorConfig(
                model=draft_model,
                provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
            ),
        ),
        object_store=object_store,
        cost_recorder_factory=_cost_recorder,
        provider_name=_DEFAULT_LLM_PROVIDER_NAME,
        provider_operation=LLMProviderOperation.CHAT_COMPLETIONS.value,
    )


def _normalize_database_urls(database_url: str) -> tuple[URL, PsycopgConnectKwargs]:
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
    async_database_url = url.set(drivername=f"{normalized_driver}+{async_driver}")
    probe_database_url = url.set(drivername=normalized_driver)
    return async_database_url, _psycopg_connection_kwargs(probe_database_url)


def _query_param_scalar(value: str | tuple[str, ...]) -> str:
    """Return a query-parameter value as a plain comma-joined string."""
    return ",".join(value) if isinstance(value, tuple) else value


def _apply_query_connect_overrides(
    probe_kwargs: PsycopgConnectKwargs, url: URL
) -> None:
    """Apply psycopg connection kwargs that SQLAlchemy stores in the query."""
    if host := url.query.get("host"):
        probe_kwargs["host"] = _query_param_scalar(host)
    if port := url.query.get("port"):
        probe_kwargs["port"] = int(_query_param_scalar(port))
    if sslmode := url.query.get("sslmode"):
        probe_kwargs["sslmode"] = _query_param_scalar(sslmode)


def _psycopg_connection_kwargs(url: URL) -> PsycopgConnectKwargs:
    """Return Psycopg connection kwargs without rendering secrets into a URL."""
    connection_kwargs = url.translate_connect_args(
        username="user",
        database="dbname",
    )
    probe_kwargs = PsycopgConnectKwargs()
    if value := connection_kwargs.get("host"):
        probe_kwargs["host"] = value
    if value := connection_kwargs.get("dbname"):
        probe_kwargs["dbname"] = value
    if value := connection_kwargs.get("user"):
        probe_kwargs["user"] = value
    if value := connection_kwargs.get("password"):
        probe_kwargs["password"] = value
    if port := connection_kwargs.get("port"):
        probe_kwargs["port"] = int(port)
    _apply_query_connect_overrides(probe_kwargs, url)
    return probe_kwargs


def create_app_from_env() -> asgi.App:
    """Build the Falcon ASGI service from environment configuration."""
    config = _load_runtime_config()
    database_probe, uow_factory, shutdown_hook = _build_database_probe(
        config.database_url
    )
    object_store = FilesystemObjectStore(config.source_intake_object_store_root)
    launcher = _build_generation_launcher(
        uow_factory,
        None,
        object_store=object_store,
    )
    shutdown_hooks = (
        (shutdown_hook,)
        if launcher is None
        else (
            shutdown_hook,
            launcher.shutdown,
        )
    )
    return create_app(
        ApiDependencies(
            uow_factory=uow_factory,
            object_store=object_store,
            readiness_probes=(database_probe,),
            shutdown_hooks=shutdown_hooks,
            launcher=launcher,
        )
    )
