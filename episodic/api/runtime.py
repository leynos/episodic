"""Granian runtime composition root for the Falcon ASGI service."""

import dataclasses as dc
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
from episodic.llm import LLMProviderOperation, LLMTokenBudget
from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from episodic.observability import StructuredLogMetrics, StructuredLogTracer

from . import create_app
from .authorization import StaticBearerTokenAuthorization
from .dependencies import ApiDependencies, ReadinessProbe, ShutdownHook
from .runtime_config import (
    RuntimeConfig,
    _load_runtime_config,
)
from .runtime_config import (
    RuntimeConfigurationError as RuntimeConfigurationError,
)

if typ.TYPE_CHECKING:
    from falcon import asgi

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.llm import LLMPort
    from episodic.observability import MetricsPort, ValueMetricsPort

    from .types import UowFactory


@dc.dataclass(frozen=True, slots=True)
class _GenerationLauncherRuntime:
    """Composition inputs for the in-process generation launcher."""

    metrics: ValueMetricsPort
    object_store: ObjectStorePort | None = None


_SUPPORTED_POSTGRES_DRIVERS = frozenset({"postgres", "postgresql"})
_SUPPORTED_ASYNC_POSTGRES_DRIVERS = frozenset({"asyncpg", "psycopg"})
_DEFAULT_ASYNC_POSTGRES_DRIVER = "psycopg"
GRANIAN_FACTORY_TARGET = "episodic.api.runtime:create_app_from_env"
GRANIAN_INTERFACE = "asgi"
HTTP_BIND_PORT = 8080
_DEFAULT_LLM_PROVIDER_NAME = "openai"
_DRAFT_MAX_INPUT_TOKENS = 32_768


class PsycopgConnectKwargs(typ.TypedDict, total=False):
    """Connection kwargs accepted by the database readiness probe."""

    host: str
    port: int
    dbname: str
    user: str
    password: str
    sslmode: str


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
    *,
    config: RuntimeConfig,
) -> InProcessGenerationRunLauncher:
    """Build the no-QA generation-run launcher when an LLM port is configured."""
    pricing_catalogue = FilePricingCatalogue(config.pricing_snapshot_directory)

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
                model=config.draft_model,
                provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
                token_budget=LLMTokenBudget(
                    max_input_tokens=_DRAFT_MAX_INPUT_TOKENS,
                    max_output_tokens=config.generation_max_output_tokens,
                    max_total_tokens=(
                        _DRAFT_MAX_INPUT_TOKENS + config.generation_max_output_tokens
                    ),
                ),
                max_response_bytes=config.generation_max_response_bytes,
            ),
        ),
        object_store=runtime.object_store,
        cost_recorder_factory=_cost_recorder,
        provider_name=_DEFAULT_LLM_PROVIDER_NAME,
        provider_operation=LLMProviderOperation.CHAT_COMPLETIONS.value,
        metrics=runtime.metrics,
        tracer=StructuredLogTracer(),
        source_limits=config.generation_source_limits,
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
            ),
            config=config,
        )

        async def shutdown_generation() -> None:
            """Stop generation work before closing its provider client."""
            try:
                await launcher.shutdown()
            finally:
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
            generation_source_limits=config.generation_source_limits,
            tracer=tracer,
            authorization=StaticBearerTokenAuthorization(
                token=config.authorization_bearer_token,
                principal_id=config.authorization_principal_id,
            ),
        )
    )
