"""Tests for the Celery worker scaffold."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from kombu import Queue

    from episodic.worker import (
        CpuDiagnosticRequest,
        CpuDiagnosticResult,
        IoDiagnosticRequest,
        IoDiagnosticResult,
    )


@dc.dataclass(slots=True)
class _FakeIoDiagnostic:
    """Record an I/O-bound diagnostic request and return a canned response."""

    seen_messages: list[str]

    def __call__(self, request: IoDiagnosticRequest) -> IoDiagnosticResult:
        from episodic.worker import IoDiagnosticResult

        self.seen_messages.append(request.message)
        return IoDiagnosticResult(
            message=request.message,
            correlation_id=request.correlation_id,
            worker_kind="io-bound",
        )


@dc.dataclass(slots=True)
class _FakeCpuDiagnostic:
    """Record a CPU-bound diagnostic request and return a canned response."""

    seen_iterations: list[int]

    def __call__(self, request: CpuDiagnosticRequest) -> CpuDiagnosticResult:
        from episodic.worker import CpuDiagnosticResult

        self.seen_iterations.append(request.iterations)
        return CpuDiagnosticResult(
            digest=f"digest-{request.iterations}",
            iterations=request.iterations,
            worker_kind="cpu-bound",
        )


def _runtime_environ() -> dict[str, str]:
    return {
        "EPISODIC_CELERY_BROKER_URL": "amqp://guest:guest@localhost:5672//",
        "EPISODIC_CELERY_ALWAYS_EAGER": "true",
    }


def test_worker_topology_defines_io_and_cpu_queues() -> None:
    """Expose the canonical queue, exchange, and routing-key taxonomy."""
    from episodic.worker import DEFAULT_WORKER_TOPOLOGY, WorkloadClass

    assert DEFAULT_WORKER_TOPOLOGY.exchange_name == "episodic.tasks"
    assert DEFAULT_WORKER_TOPOLOGY.exchange_type == "topic"
    assert DEFAULT_WORKER_TOPOLOGY.default_workload is WorkloadClass.IO_BOUND

    io_queue = DEFAULT_WORKER_TOPOLOGY.queue_for(WorkloadClass.IO_BOUND)
    cpu_queue = DEFAULT_WORKER_TOPOLOGY.queue_for(WorkloadClass.CPU_BOUND)

    assert io_queue.name == "episodic.io"
    assert io_queue.routing_key == "episodic.io.#"
    assert cpu_queue.name == "episodic.cpu"
    assert cpu_queue.routing_key == "episodic.cpu.#"


def test_load_runtime_config_requires_rabbitmq_broker_url() -> None:
    """Reject missing or non-AMQP broker URLs for the worker runtime."""
    from episodic.worker import load_runtime_config

    with pytest.raises(RuntimeError, match="EPISODIC_CELERY_BROKER_URL"):
        load_runtime_config({})

    with pytest.raises(RuntimeError, match="RabbitMQ"):
        load_runtime_config({"EPISODIC_CELERY_BROKER_URL": "redis://localhost/0"})


def test_build_worker_launch_profiles_maps_workloads_to_distinct_pools() -> None:
    """Capture the documented pool split between I/O and CPU workloads."""
    from episodic.worker import (
        WorkerPool,
        WorkloadClass,
        build_worker_launch_profiles,
        load_runtime_config,
    )

    config = load_runtime_config({
        **_runtime_environ(),
        "EPISODIC_CELERY_IO_POOL": "eventlet",
        "EPISODIC_CELERY_IO_CONCURRENCY": "128",
        "EPISODIC_CELERY_CPU_CONCURRENCY": "6",
    })

    profiles = build_worker_launch_profiles(config)

    assert profiles[WorkloadClass.IO_BOUND].pool is WorkerPool.EVENTLET
    assert profiles[WorkloadClass.IO_BOUND].concurrency == 128
    assert profiles[WorkloadClass.IO_BOUND].queue_name == "episodic.io"
    assert profiles[WorkloadClass.CPU_BOUND].pool is WorkerPool.PREFORK
    assert profiles[WorkloadClass.CPU_BOUND].concurrency == 6
    assert profiles[WorkloadClass.CPU_BOUND].queue_name == "episodic.cpu"


def test_create_celery_app_registers_task_routes_and_queues() -> None:
    """Configure the documented queue topology on the Celery app."""
    from episodic.worker import (
        CPU_DIAGNOSTIC_TASK_NAME,
        DEFAULT_WORKER_TOPOLOGY,
        IO_DIAGNOSTIC_TASK_NAME,
        create_celery_app,
        load_runtime_config,
    )

    app = create_celery_app(load_runtime_config(_runtime_environ()))
    queues = typ.cast("tuple[Queue, ...]", app.conf.task_queues)

    assert app.conf.task_default_exchange == DEFAULT_WORKER_TOPOLOGY.exchange_name
    assert {queue.name for queue in queues} == {"episodic.io", "episodic.cpu"}
    assert (
        typ.cast("dict[str, str]", app.conf.task_routes[IO_DIAGNOSTIC_TASK_NAME])[
            "queue"
        ]
        == "episodic.io"
    )
    assert (
        typ.cast("dict[str, str]", app.conf.task_routes[CPU_DIAGNOSTIC_TASK_NAME])[
            "queue"
        ]
        == "episodic.cpu"
    )
    assert IO_DIAGNOSTIC_TASK_NAME in app.tasks
    assert CPU_DIAGNOSTIC_TASK_NAME in app.tasks


def test_create_celery_app_executes_representative_tasks_through_dependencies() -> None:
    """Run eager tasks and prove that the task bodies depend on typed seams."""
    from episodic.worker import (
        CPU_DIAGNOSTIC_TASK_NAME,
        IO_DIAGNOSTIC_TASK_NAME,
        WorkerDependencies,
        create_celery_app,
        load_runtime_config,
    )

    io_handler = _FakeIoDiagnostic(seen_messages=[])
    cpu_handler = _FakeCpuDiagnostic(seen_iterations=[])
    app = create_celery_app(
        load_runtime_config(_runtime_environ()),
        WorkerDependencies(
            io_diagnostic=io_handler,
            cpu_diagnostic=cpu_handler,
        ),
    )

    io_result = app.tasks[IO_DIAGNOSTIC_TASK_NAME].delay({
        "message": "hello",
        "correlation_id": "trace-1",
    })
    cpu_result = app.tasks[CPU_DIAGNOSTIC_TASK_NAME].delay({
        "message": "hello",
        "iterations": 4,
    })

    assert io_handler.seen_messages == ["hello"]
    assert cpu_handler.seen_iterations == [4]
    assert io_result.get() == {
        "message": "hello",
        "correlation_id": "trace-1",
        "worker_kind": "io-bound",
    }
    assert cpu_result.get() == {
        "digest": "digest-4",
        "iterations": 4,
        "worker_kind": "cpu-bound",
    }


def test_create_celery_app_from_env_reads_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose an environment-driven worker runtime composition root."""
    from episodic.worker import create_celery_app_from_env

    monkeypatch.setenv(
        "EPISODIC_CELERY_BROKER_URL",
        "amqp://guest:guest@localhost:5672//",
    )
    monkeypatch.setenv("EPISODIC_CELERY_ALWAYS_EAGER", "true")

    app = create_celery_app_from_env()

    assert app.conf.broker_url == "amqp://guest:guest@localhost:5672//"
    assert bool(app.conf.task_always_eager) is True
