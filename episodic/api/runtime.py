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
from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from episodic.logging import get_logger, log_info, log_warning
from episodic.observability import StructuredLogMetrics, StructuredLogTracer

from . import create_app
from .dependencies import ApiDependencies, ReadinessProbe, ShutdownHook

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from falcon import asgi

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.llm import LLMPort
    from episodic.observability import MetricsPort, ValueMetricsPort

    from .types import UowFactory


@dc.dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Runtime configuration required to boot the Falcon HTTP service."""

    database_url: str
    source_intake_object_store_root: pathlib.Path
    llm_base_url: str | None
    llm_api_key: str | None
    draft_model: str
    pricing_snapshot_directory: pathlib.Path


@dc.dataclass(frozen=True, slots=True)
class _GenerationLauncherRuntime:
    """Composition inputs for the in-process generation launcher."""

    metrics: ValueMetricsPort
    object_store: ObjectStorePort | None = None
    config: RuntimeConfig | None = None


_SUPPORTED_POSTGRES_DRIVERS = frozenset({"postgres", "postgresql"})
_SUPPORTED_ASYNC_POSTGRES_DRIVERS = frozenset({"asyncpg", "psycopg"})
_DEFAULT_ASYNC_POSTGRES_DRIVER = "psycopg"
GRANIAN_FACTORY_TARGET = "episodic.api.runtime:create_app_from_env"
GRANIAN_INTERFACE = "asgi"
HTTP_BIND_PORT = 8080
_DEFAULT_DRAFT_MODEL = "gpt-4o-mini"
_DEFAULT_LLM_PROVIDER_NAME = "openai"
_REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEFAULT_PRICING_DIRECTORY = _REPOSITORY_ROOT / "config/pricing-snapshots"
_PRICING_DIRECTORY_SETTING = "PRICING_SNAPSHOT_DIRECTORY"


class RuntimeConfigurationError(RuntimeError):
    """Raised when required HTTP-runtime configuration is invalid."""


class PsycopgConnectKwargs(typ.TypedDict, total=False):
    """Connection kwargs accepted by the database readiness probe."""

    host: str
    port: int
    dbname: str
    user: str
    password: str
    sslmode: str


logger = get_logger(__name__)


def _required_setting(
    environment: cabc.Mapping[str, str],
    name: str,
    error_message: str,
) -> str:
    """Return a required, non-empty environment setting."""
    value = environment.get(name, "").strip()
    if not value:
        raise RuntimeConfigurationError(error_message)
    return value


def _llm_settings(
    environment: cabc.Mapping[str, str],
) -> tuple[str | None, str | None]:
    """Return the optional, paired OpenAI-compatible provider settings."""
    base_url = environment.get("OPENAI_BASE_URL", "").strip() or None
    api_key = environment.get("OPENAI_API_KEY", "").strip() or None
    if (base_url is None) != (api_key is None):
        msg = "OPENAI_BASE_URL and OPENAI_API_KEY must be configured together."
        raise RuntimeConfigurationError(msg)
    return base_url, api_key


def _pricing_snapshot_directory(
    environment: cabc.Mapping[str, str],
) -> pathlib.Path:
    """Return the configured immutable pricing-catalogue directory."""
    configured = environment.get(_PRICING_DIRECTORY_SETTING, "").strip()
    candidate = pathlib.Path(configured) if configured else _DEFAULT_PRICING_DIRECTORY
    directory = candidate if candidate.is_absolute() else _REPOSITORY_ROOT / candidate
    resolved = directory.resolve()
    if not resolved.is_dir():
        msg = f"{_PRICING_DIRECTORY_SETTING} must name an existing directory."
        raise RuntimeConfigurationError(msg)
    return resolved


def _load_runtime_config(
    environ: cabc.Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Read and validate runtime configuration from environment variables."""
    environment = os.environ if environ is None else environ
    database_url = _required_setting(
        environment,
        "DATABASE_URL",
        "DATABASE_URL must be set before starting the HTTP service.",
    )
    try:
        object_store_root = _required_setting(
            environment,
            "SOURCE_INTAKE_OBJECT_STORE_ROOT",
            "SOURCE_INTAKE_OBJECT_STORE_ROOT must be set before starting "
            "the HTTP service.",
        )
    except RuntimeConfigurationError:
        log_warning(
            logger,
            "runtime_config_missing setting=%s",
            "SOURCE_INTAKE_OBJECT_STORE_ROOT",
        )
        raise
    llm_base_url, llm_api_key = _llm_settings(environment)
    draft_model = (
        _required_setting(
            environment,
            "DRAFT_MODEL",
            "DRAFT_MODEL must be a non-empty string.",
        )
        if "DRAFT_MODEL" in environment
        else _DEFAULT_DRAFT_MODEL
    )
    pricing_snapshot_directory = _pricing_snapshot_directory(environment)
    log_info(
        logger,
        "runtime_config_loaded source_intake_object_store_configured",
    )
    return RuntimeConfig(
        database_url=database_url,
        source_intake_object_store_root=pathlib.Path(object_store_root),
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        draft_model=draft_model,
        pricing_snapshot_directory=pricing_snapshot_directory,
    )


def _build_llm_port(config: RuntimeConfig) -> OpenAICompatibleLLMAdapter | None:
    """Build the environment-configured OpenAI-compatible LLM adapter."""
    if config.llm_base_url is None or config.llm_api_key is None:
        return None
    return OpenAICompatibleLLMAdapter(
        config=OpenAICompatibleLLMConfig(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        )
    )


def _build_database_probe(
    database_url: str,
    *,
    metrics: MetricsPort,
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
        return SqlAlchemyUnitOfWork(session_factory, metrics=metrics)

    return (
        ReadinessProbe(name="database", check=check_database),
        uow_factory,
        engine.dispose,
    )


def _build_generation_launcher(
    uow_factory: UowFactory,
    llm_port: LLMPort,
    runtime: _GenerationLauncherRuntime,
) -> InProcessGenerationRunLauncher:
    """Build the no-QA generation-run launcher when an LLM port is configured."""
    draft_model = (
        _DEFAULT_DRAFT_MODEL if runtime.config is None else runtime.config.draft_model
    )
    pricing_directory = (
        _DEFAULT_PRICING_DIRECTORY
        if runtime.config is None
        else runtime.config.pricing_snapshot_directory
    )
    pricing_catalogue = FilePricingCatalogue(pricing_directory)

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
        object_store=runtime.object_store,
        cost_recorder_factory=_cost_recorder,
        provider_name=_DEFAULT_LLM_PROVIDER_NAME,
        provider_operation=LLMProviderOperation.CHAT_COMPLETIONS.value,
        metrics=runtime.metrics,
        tracer=StructuredLogTracer(),
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
    metrics = StructuredLogMetrics()
    database_probe, uow_factory, shutdown_hook = _build_database_probe(
        config.database_url,
        metrics=metrics,
    )
    object_store = FilesystemObjectStore(config.source_intake_object_store_root)
    llm_port = _build_llm_port(config)
    tracer = StructuredLogTracer()
    if llm_port is None:
        launcher = None
        shutdown_hooks = (shutdown_hook,)
    else:
        launcher = _build_generation_launcher(
            uow_factory,
            llm_port,
            _GenerationLauncherRuntime(
                metrics=metrics,
                object_store=object_store,
                config=config,
            ),
        )

        async def shutdown_generation() -> None:
            """Stop generation work before closing its provider client."""
            await launcher.shutdown()
            await llm_port.aclose()

        shutdown_hooks = (shutdown_generation, shutdown_hook)
    return create_app(
        ApiDependencies(
            uow_factory=uow_factory,
            object_store=object_store,
            readiness_probes=(database_probe,),
            shutdown_hooks=shutdown_hooks,
            llm_port=llm_port,
            launcher=launcher,
            tracer=tracer,
        )
    )
