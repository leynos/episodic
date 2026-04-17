"""Celery runtime composition root for the worker scaffold."""

import dataclasses as dc
import enum
import importlib
import os
import typing as typ
from urllib.parse import urlparse

from celery import Celery

from .tasks import SCAFFOLD_TASK_WORKLOADS, WorkerDependencies, register_scaffold_tasks
from .topology import DEFAULT_WORKER_TOPOLOGY, WorkerTopology, WorkloadClass

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class WorkerPool(enum.StrEnum):
    """Supported Celery worker pools for the scaffold."""

    PREFORK = "prefork"
    GEVENT = "gevent"
    EVENTLET = "eventlet"


@dc.dataclass(frozen=True, slots=True)
class WorkerRuntimeConfig:
    """Runtime configuration required to boot the Celery worker scaffold."""

    broker_url: str
    result_backend: str | None = None
    task_always_eager: bool = False
    io_pool: WorkerPool = WorkerPool.GEVENT
    io_concurrency: int = 128
    cpu_pool: WorkerPool = WorkerPool.PREFORK
    cpu_concurrency: int = 4

    def __post_init__(self) -> None:
        """Validate runtime configuration values."""
        if not isinstance(self.io_pool, WorkerPool):
            msg = "WorkerRuntimeConfig.io_pool must be a WorkerPool value."
            raise TypeError(msg)
        if not isinstance(self.cpu_pool, WorkerPool):
            msg = "WorkerRuntimeConfig.cpu_pool must be a WorkerPool value."
            raise TypeError(msg)
        _validate_pool_backend(self.io_pool, field_name="io_pool")
        _validate_pool_backend(self.cpu_pool, field_name="cpu_pool")
        _validate_amqp_scheme(self.broker_url)
        _validate_result_backend(self.result_backend)
        _validate_positive_concurrency("io_concurrency", self.io_concurrency)
        _validate_positive_concurrency("cpu_concurrency", self.cpu_concurrency)


@dc.dataclass(frozen=True, slots=True)
class WorkerLaunchProfile:
    """Describe how one workload class should be consumed by a worker process."""

    workload: WorkloadClass
    queue_name: str
    routing_key: str
    pool: WorkerPool
    concurrency: int


def _parse_bool(environ: cabc.Mapping[str, str], *, key: str, default: bool) -> bool:
    value = environ.get(key)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    msg = f"{key} must be a boolean string such as true/false."
    raise RuntimeError(msg)


def _parse_positive_int(
    environ: cabc.Mapping[str, str],
    *,
    key: str,
    default: int,
) -> int:
    value = environ.get(key)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        msg = f"{key} must be a positive integer."
        raise RuntimeError(msg) from exc
    if parsed <= 0:
        msg = f"{key} must be a positive integer."
        raise RuntimeError(msg)
    return parsed


def _parse_pool(
    environ: cabc.Mapping[str, str],
    *,
    key: str,
    default: WorkerPool,
) -> WorkerPool:
    value = environ.get(key)
    if value is None or not value.strip():
        return default
    try:
        return WorkerPool(value.strip().lower())
    except ValueError as exc:
        msg = f"{key} must be one of prefork, gevent, or eventlet."
        raise RuntimeError(msg) from exc


def _validate_amqp_scheme(url: str) -> None:
    """Raise ValueError if broker_url does not use an AMQP scheme."""
    parsed = urlparse(url)
    if parsed.scheme not in {"amqp", "amqps", "pyamqp"}:
        msg = "WorkerRuntimeConfig.broker_url must point at RabbitMQ via AMQP."
        raise ValueError(msg)


def _validate_result_backend(backend: str | None) -> None:
    """Raise ValueError if result_backend is set but blank."""
    if backend is not None and not backend.strip():
        msg = "WorkerRuntimeConfig.result_backend cannot be blank."
        raise ValueError(msg)


def _validate_positive_concurrency(name: str, value: int) -> None:
    """Raise ValueError if a concurrency field is not positive."""
    if value <= 0:
        msg = f"WorkerRuntimeConfig.{name} must be positive."
        raise ValueError(msg)


def _validate_pool_backend(pool: WorkerPool, *, field_name: str) -> None:
    """Raise ValueError when a selected worker pool backend is unavailable."""
    if pool is WorkerPool.PREFORK:
        return
    module_name = pool.value
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        msg = (
            f"WorkerRuntimeConfig.{field_name} requires the optional "
            f"{module_name!r} backend to be installed."
        )
        raise ValueError(msg) from exc


def load_runtime_config(
    environ: cabc.Mapping[str, str] | None = None,
) -> WorkerRuntimeConfig:
    """Read and validate runtime configuration from environment variables."""
    environment = os.environ if environ is None else environ
    broker_url = environment.get("EPISODIC_CELERY_BROKER_URL", "").strip()
    if not broker_url:
        msg = "EPISODIC_CELERY_BROKER_URL must be set before starting workers."
        raise RuntimeError(msg)
    try:
        return WorkerRuntimeConfig(
            broker_url=broker_url,
            result_backend=environment.get("EPISODIC_CELERY_RESULT_BACKEND"),
            task_always_eager=_parse_bool(
                environment,
                key="EPISODIC_CELERY_ALWAYS_EAGER",
                default=False,
            ),
            io_pool=_parse_pool(
                environment,
                key="EPISODIC_CELERY_IO_POOL",
                default=WorkerPool.GEVENT,
            ),
            io_concurrency=_parse_positive_int(
                environment,
                key="EPISODIC_CELERY_IO_CONCURRENCY",
                default=128,
            ),
            cpu_pool=_parse_pool(
                environment,
                key="EPISODIC_CELERY_CPU_POOL",
                default=WorkerPool.PREFORK,
            ),
            cpu_concurrency=_parse_positive_int(
                environment,
                key="EPISODIC_CELERY_CPU_CONCURRENCY",
                default=4,
            ),
        )
    except ValueError as exc:
        msg = "RabbitMQ-backed worker configuration is invalid."
        raise RuntimeError(msg) from exc


def build_worker_launch_profiles(
    config: WorkerRuntimeConfig,
    topology: WorkerTopology = DEFAULT_WORKER_TOPOLOGY,
) -> dict[WorkloadClass, WorkerLaunchProfile]:
    """Build per-workload launch profiles from runtime configuration."""
    io_queue = topology.queue_for(WorkloadClass.IO_BOUND)
    cpu_queue = topology.queue_for(WorkloadClass.CPU_BOUND)
    return {
        WorkloadClass.IO_BOUND: WorkerLaunchProfile(
            workload=WorkloadClass.IO_BOUND,
            queue_name=io_queue.name,
            routing_key=io_queue.diagnostic_routing_key,
            pool=config.io_pool,
            concurrency=config.io_concurrency,
        ),
        WorkloadClass.CPU_BOUND: WorkerLaunchProfile(
            workload=WorkloadClass.CPU_BOUND,
            queue_name=cpu_queue.name,
            routing_key=cpu_queue.diagnostic_routing_key,
            pool=config.cpu_pool,
            concurrency=config.cpu_concurrency,
        ),
    }


def create_celery_app(
    config: WorkerRuntimeConfig,
    dependencies: WorkerDependencies | None = None,
    topology: WorkerTopology = DEFAULT_WORKER_TOPOLOGY,
) -> Celery:
    """Build and return the Celery worker scaffold application."""
    worker_dependencies = WorkerDependencies() if dependencies is None else dependencies
    app = Celery(
        "episodic.worker", broker=config.broker_url, backend=config.result_backend
    )
    default_queue = topology.queue_for(topology.default_workload)
    app.conf.update(
        broker_url=config.broker_url,
        result_backend=config.result_backend,
        task_always_eager=config.task_always_eager,
        task_store_eager_result=config.task_always_eager,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_default_exchange=topology.exchange_name,
        task_default_exchange_type=topology.exchange_type,
        task_default_queue=default_queue.name,
        task_default_routing_key=default_queue.diagnostic_routing_key,
        task_create_missing_queues=False,
        task_queues=topology.kombu_queues(),
        task_routes=topology.task_routes(SCAFFOLD_TASK_WORKLOADS),
    )
    register_scaffold_tasks(app, worker_dependencies)
    return app


def create_celery_app_from_env() -> Celery:
    """Build the Celery worker scaffold from environment configuration."""
    return create_celery_app(load_runtime_config())
