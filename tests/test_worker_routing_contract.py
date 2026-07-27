"""Tests for explicit Celery worker routing contracts."""

import dataclasses as dc
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


@dc.dataclass(slots=True)
class _FakeWorkerLogger:
    """Capture worker runtime log messages."""

    infos: list[str]
    exceptions: list[str]

    def info(self, message: str) -> None:
        self.infos += [message]

    def exception(self, message: str) -> None:
        self.exceptions += [message]


def _runtime_environ() -> dict[str, str]:
    return {
        "EPISODIC_CELERY_BROKER_URL": "amqp://guest:guest@localhost:5672//",
        "EPISODIC_CELERY_ALWAYS_EAGER": "true",
    }


def test_scaffold_task_workload_mapping_matches_registered_task_names() -> None:
    """Require each registered scaffold task to have one explicit workload."""
    from episodic.worker.tasks import SCAFFOLD_TASK_NAMES, SCAFFOLD_TASK_WORKLOADS

    workload_task_names = set(SCAFFOLD_TASK_WORKLOADS)
    registered_task_names = set(SCAFFOLD_TASK_NAMES)

    assert workload_task_names == registered_task_names, (
        "scaffold task workloads must match scaffold task names: "
        f"workloads={workload_task_names!r}, registered={registered_task_names!r}"
    )


def test_task_routes_include_exchange_metadata_for_each_task(
    snapshot: SnapshotAssertion,
) -> None:
    """Expose complete Celery route metadata for each classified task."""
    from episodic.worker import (
        CPU_DIAGNOSTIC_TASK_NAME,
        DEFAULT_WORKER_TOPOLOGY,
        IO_DIAGNOSTIC_TASK_NAME,
    )
    from episodic.worker.tasks import SCAFFOLD_TASK_WORKLOADS

    routes = DEFAULT_WORKER_TOPOLOGY.task_routes(SCAFFOLD_TASK_WORKLOADS)

    assert routes[IO_DIAGNOSTIC_TASK_NAME] == snapshot, (
        "actual output must match snapshot"
    )
    assert routes[CPU_DIAGNOSTIC_TASK_NAME] == snapshot, (
        "actual output must match snapshot"
    )


def test_task_routes_reject_malformed_task_names_and_workloads() -> None:
    """Reject malformed task route tables instead of producing fallback routes."""
    from episodic.worker import DEFAULT_WORKER_TOPOLOGY, WorkloadClass

    malformed_task_names = (
        "",
        "singlepart",
        "a..b",
        ".leading",
        "trailing.",
        " valid.name ",
        "\tname.part",
        "episodic.worker. io",
    )
    for malformed_task_name in malformed_task_names:
        malformed_task_workloads = {
            malformed_task_name: WorkloadClass.IO_BOUND,
            "episodic.worker.cpu_diagnostic": WorkloadClass.CPU_BOUND,
        }
        with pytest.raises(
            ValueError,
            match=r"Worker task names must be non-empty dotted names\.",
        ):
            DEFAULT_WORKER_TOPOLOGY.task_routes(malformed_task_workloads)

    with pytest.raises(
        TypeError,
        match=r"Worker task names must be non-empty dotted names\.",
    ):
        DEFAULT_WORKER_TOPOLOGY.task_routes({
            typ.cast("str", 42): WorkloadClass.IO_BOUND,
        })

    with pytest.raises(
        TypeError,
        match=r"Worker task workloads must be WorkloadClass values\.",
    ):
        DEFAULT_WORKER_TOPOLOGY.task_routes({
            "episodic.worker.io_diagnostic": typ.cast("WorkloadClass", "io_bound"),
        })


def test_create_celery_app_logs_task_route_materialisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Log route-table materialisation for worker startup diagnosis."""
    from episodic.worker import create_celery_app, load_runtime_config
    from episodic.worker import runtime as runtime_module

    logger = _FakeWorkerLogger(infos=[], exceptions=[])
    monkeypatch.setattr(runtime_module, "logger", logger)

    create_celery_app(load_runtime_config(_runtime_environ()))

    assert logger.infos == [
        "Building Celery worker task routes for 2 tasks.",
        "Built Celery worker task routes for 2 tasks.",
    ], "Expected values to match"
    assert not logger.exceptions, "Expected condition to be false"


def test_create_celery_app_logs_task_route_validation_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Log invalid route-table context before propagating startup failures."""
    from episodic.worker import WorkloadClass
    from episodic.worker import runtime as runtime_module

    logger = _FakeWorkerLogger(infos=[], exceptions=[])
    monkeypatch.setattr(runtime_module, "logger", logger)

    with pytest.raises(
        TypeError,
        match=r"Worker task names must be non-empty dotted names\.",
    ):
        runtime_module._build_task_routes(
            runtime_module.DEFAULT_WORKER_TOPOLOGY,
            {typ.cast("str", 42): WorkloadClass.IO_BOUND},
        )

    assert logger.infos == ["Building Celery worker task routes for 1 tasks."], (
        "Expected values to match"
    )
    assert len(logger.exceptions) == 1, "Expected values to match"
    assert "tasks=(42,)" in logger.exceptions[0], (
        "Expected collection to contain the value"
    )
    assert (
        "workloads=(<WorkloadClass.IO_BOUND: 'io_bound'>,)" in logger.exceptions[0]
    ), "Expected collection to contain the value"
    assert (
        "Worker task names must be non-empty dotted names." in logger.exceptions[0]
    ), "Expected collection to contain the value"
