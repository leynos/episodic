"""Tests for explicit Celery worker routing contracts."""

import typing as typ

import pytest


def test_scaffold_task_workload_mapping_matches_registered_task_names() -> None:
    """Require each registered scaffold task to have one explicit workload."""
    from episodic.worker.tasks import SCAFFOLD_TASK_NAMES, SCAFFOLD_TASK_WORKLOADS

    workload_task_names = set(SCAFFOLD_TASK_WORKLOADS)
    registered_task_names = set(SCAFFOLD_TASK_NAMES)

    assert workload_task_names == registered_task_names, (
        "scaffold task workloads must match scaffold task names: "
        f"workloads={workload_task_names!r}, registered={registered_task_names!r}"
    )


def test_task_routes_include_exchange_metadata_for_each_task() -> None:
    """Expose complete Celery route metadata for each classified task."""
    from episodic.worker import (
        CPU_DIAGNOSTIC_TASK_NAME,
        DEFAULT_WORKER_TOPOLOGY,
        IO_DIAGNOSTIC_TASK_NAME,
    )
    from episodic.worker.tasks import SCAFFOLD_TASK_WORKLOADS

    routes = DEFAULT_WORKER_TOPOLOGY.task_routes(SCAFFOLD_TASK_WORKLOADS)

    assert routes[IO_DIAGNOSTIC_TASK_NAME] == {
        "queue": "episodic.io",
        "exchange": "episodic.tasks",
        "exchange_type": "topic",
        "routing_key": "episodic.io.diagnostic",
    }, f"I/O task routing contract failed for {IO_DIAGNOSTIC_TASK_NAME}: {routes!r}"
    assert routes[CPU_DIAGNOSTIC_TASK_NAME] == {
        "queue": "episodic.cpu",
        "exchange": "episodic.tasks",
        "exchange_type": "topic",
        "routing_key": "episodic.cpu.diagnostic",
    }, f"CPU task routing contract failed for {CPU_DIAGNOSTIC_TASK_NAME}: {routes!r}"


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
        match=r"Worker task workloads must be WorkloadClass values\.",
    ):
        DEFAULT_WORKER_TOPOLOGY.task_routes({
            "episodic.worker.io_diagnostic": typ.cast("WorkloadClass", "io_bound"),
        })
