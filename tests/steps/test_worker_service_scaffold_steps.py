"""Behavioural tests for the Celery worker scaffold."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import pytest
from pytest_bdd import given, scenario, then, when

if typ.TYPE_CHECKING:
    from celery import Celery

    from episodic.worker import WorkerLaunchProfile, WorkloadClass


@dc.dataclass(slots=True)
class WorkerServiceScaffoldContext:
    """Shared state for worker scaffold behavioural steps."""

    app: Celery | None = None
    routes: dict[str, dict[str, str]] = dc.field(default_factory=dict)
    io_result: dict[str, object] | None = None
    cpu_result: dict[str, object] | None = None
    profiles: dict[WorkloadClass, WorkerLaunchProfile] = dc.field(default_factory=dict)


@pytest.fixture
def worker_service_scaffold_context() -> WorkerServiceScaffoldContext:
    """Provide mutable context for the BDD scenario."""
    return WorkerServiceScaffoldContext()


@scenario(
    "../features/worker_service_scaffold.feature",
    "The worker scaffold exposes documented routing and task seams",
)
def test_worker_scaffold_contract() -> None:
    """Run the worker scaffold contract scenario."""


@given("a worker scaffold environment")
def given_worker_scaffold_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure the worker runtime as an eager contract test."""
    monkeypatch.setenv(
        "EPISODIC_CELERY_BROKER_URL",
        "amqp://guest:guest@localhost:5672//",
    )
    monkeypatch.setenv("EPISODIC_CELERY_ALWAYS_EAGER", "true")
    monkeypatch.setenv("EPISODIC_CELERY_IO_CONCURRENCY", "64")
    monkeypatch.setenv("EPISODIC_CELERY_CPU_CONCURRENCY", "4")


@when("the Celery worker app is created from environment configuration")
def when_worker_app_is_created(
    worker_service_scaffold_context: WorkerServiceScaffoldContext,
) -> None:
    """Build the worker app through the public runtime factory."""
    from episodic.worker import (
        build_worker_launch_profiles,
        create_celery_app_from_env,
        load_runtime_config,
    )

    worker_service_scaffold_context.app = create_celery_app_from_env()
    worker_service_scaffold_context.profiles = build_worker_launch_profiles(
        load_runtime_config()
    )


@when("an operator inspects the worker routing")
def when_operator_inspects_worker_routing(
    worker_service_scaffold_context: WorkerServiceScaffoldContext,
) -> None:
    """Capture the task-route metadata exposed by the Celery app."""
    if worker_service_scaffold_context.app is None:
        msg = "Worker app has not been created."
        raise RuntimeError(msg)
    worker_service_scaffold_context.routes = typ.cast(
        "dict[str, dict[str, str]]",
        worker_service_scaffold_context.app.conf.task_routes,
    )


@when("the operator dispatches the representative diagnostic tasks")
def when_operator_dispatches_representative_tasks(
    worker_service_scaffold_context: WorkerServiceScaffoldContext,
) -> None:
    """Execute both representative tasks through Celery eager mode."""
    from episodic.worker import CPU_DIAGNOSTIC_TASK_NAME, IO_DIAGNOSTIC_TASK_NAME

    if worker_service_scaffold_context.app is None:
        msg = "Worker app has not been created."
        raise RuntimeError(msg)
    worker_service_scaffold_context.io_result = typ.cast(
        "dict[str, object]",
        worker_service_scaffold_context.app
        .tasks[IO_DIAGNOSTIC_TASK_NAME]
        .delay({"message": "bdd-io", "correlation_id": "bdd-trace"})
        .get(),
    )
    worker_service_scaffold_context.cpu_result = typ.cast(
        "dict[str, object]",
        worker_service_scaffold_context.app
        .tasks[CPU_DIAGNOSTIC_TASK_NAME]
        .delay({"message": "bdd-cpu", "iterations": 3})
        .get(),
    )


def _assert_task_contract(
    routes: dict[str, dict[str, str]],
    task_name: str,
    expected_route: dict[str, str],
    actual_result: dict[str, object] | None,
    expected_result: dict[str, object],
) -> None:
    """Assert that a task's route and execution result match the documented contract."""
    assert routes[task_name] == expected_route
    assert actual_result == expected_result


@then("the I/O-bound task targets the I/O queue and succeeds")
def then_io_task_targets_io_queue(
    worker_service_scaffold_context: WorkerServiceScaffoldContext,
) -> None:
    """Assert the documented I/O routing and response contract."""
    from episodic.worker import IO_DIAGNOSTIC_TASK_NAME

    _assert_task_contract(
        worker_service_scaffold_context.routes,
        IO_DIAGNOSTIC_TASK_NAME,
        {"queue": "episodic.io", "routing_key": "episodic.io.diagnostic"},
        worker_service_scaffold_context.io_result,
        {
            "message": "bdd-io",
            "correlation_id": "bdd-trace",
            "worker_kind": "io-bound",
        },
    )


@then("the CPU-bound task targets the CPU queue and succeeds")
def then_cpu_task_targets_cpu_queue(
    worker_service_scaffold_context: WorkerServiceScaffoldContext,
) -> None:
    """Assert the documented CPU routing and response contract."""
    from episodic.worker import CPU_DIAGNOSTIC_TASK_NAME

    _assert_task_contract(
        worker_service_scaffold_context.routes,
        CPU_DIAGNOSTIC_TASK_NAME,
        {"queue": "episodic.cpu", "routing_key": "episodic.cpu.diagnostic"},
        worker_service_scaffold_context.cpu_result,
        {
            "digest": (
                "49cc6085bf11501a3f8634450ef3eefdbf52359aee0e7b0c2deb7407829b2ba8"
            ),
            "iterations": 3,
            "worker_kind": "cpu-bound",
        },
    )


@then("the worker launch profiles map I/O and CPU workloads to distinct pools")
def then_worker_launch_profiles_are_distinct(
    worker_service_scaffold_context: WorkerServiceScaffoldContext,
) -> None:
    """Assert that workload classes expose different pool profiles."""
    from episodic.worker import WorkerPool, WorkloadClass

    io_profile = worker_service_scaffold_context.profiles[WorkloadClass.IO_BOUND]
    cpu_profile = worker_service_scaffold_context.profiles[WorkloadClass.CPU_BOUND]

    assert io_profile.pool is WorkerPool.GEVENT
    assert io_profile.concurrency == 64
    assert cpu_profile.pool is WorkerPool.PREFORK
    assert cpu_profile.concurrency == 4
