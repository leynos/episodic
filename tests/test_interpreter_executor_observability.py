"""Observability tests for interpreter CPU task executors."""

from __future__ import annotations

import concurrent.futures as cf
import dataclasses as dc
import typing as typ

import pytest

import episodic.concurrent_interpreters as ci
from tests.conftest import square_executor_value as _square

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def _shutdown_if_supported(executor: ci.CpuTaskExecutor) -> None:
    """Shut down executor implementations that own runtime resources."""
    shutdown = getattr(executor, "shutdown", None)
    if shutdown is not None:
        shutdown()


@dc.dataclass(slots=True)
class _FakeCpuTaskExecutorMetrics:
    """Capture executor metrics for observability assertions."""

    counters: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)
    observations: list[tuple[str, float, dict[str, str]]] = dc.field(
        default_factory=list,
    )

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record an observed latency measurement."""
        self.observations.append((name, value, dict(labels)))

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record an observed non-latency measurement."""
        self.observations.append((name, value, dict(labels)))


@dc.dataclass(slots=True)
class _FakeCpuTaskExecutorClock:
    """Return deterministic monotonic timestamps for executor tests."""

    timestamps: list[float]

    def monotonic_seconds(self) -> float:
        """Return the next configured timestamp."""
        return self.timestamps.pop(0)


@dc.dataclass(slots=True)
class _FakeLogger:
    """Capture logger calls without depending on process-wide logging config."""

    messages: list[str] = dc.field(default_factory=list)

    def info(self, message: str, **kwargs: object) -> None:
        """Record an info-level message."""
        del kwargs
        self.messages.append(message)

    def exception(self, message: str, **kwargs: object) -> None:
        """Record an exception-level message."""
        del kwargs
        self.messages.append(message)


@pytest.mark.asyncio
async def test_interpreter_executor_records_lifecycle_observability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interpreter-pool creation, map utilisation, and shutdown emit signals."""
    metrics = _FakeCpuTaskExecutorMetrics()
    clock = _FakeCpuTaskExecutorClock(timestamps=[1.0, 1.025])
    logger = _FakeLogger()
    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        lambda max_workers: cf.ThreadPoolExecutor(max_workers=max_workers),
    )
    monkeypatch.setattr(ci, "_log", logger)
    executor = ci.InterpreterPoolCpuTaskExecutor(
        max_workers=1,
        metrics=metrics,
        clock=clock,
    )

    try:
        results = await executor.map_ordered(_square, (2, 3))
    finally:
        executor.shutdown()

    assert results == [4, 9]
    assert (
        "interpreter_pool.map.calls",
        {"outcome": "success"},
    ) in metrics.counters
    assert (
        "interpreter_pool.map.items",
        2.0,
        {"outcome": "success"},
    ) in metrics.observations
    assert (
        "interpreter_pool.creations",
        {"outcome": "success"},
    ) in metrics.counters
    assert (
        "interpreter_pool.shutdown.latency_ms",
        pytest.approx(25.0),
        {"outcome": "success"},
    ) in metrics.observations
    assert "Created interpreter-pool executor" in logger.messages
    assert "Shut down interpreter-pool executor" in logger.messages


def test_builder_records_executor_selection_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Builder fallback and pool selections increment bounded counters."""
    metrics = _FakeCpuTaskExecutorMetrics()

    disabled_executor = ci.build_cpu_task_executor_from_environment(
        {},
        metrics=metrics,
    )
    unsupported_executor = ci.build_cpu_task_executor_from_environment(
        {"EPISODIC_USE_INTERPRETER_POOL": "1"},
        metrics=metrics,
        _capability_check=lambda: False,
    )
    executor = ci.build_cpu_task_executor_from_environment(
        {"EPISODIC_USE_INTERPRETER_POOL": "1"},
        metrics=metrics,
        _capability_check=lambda: True,
    )
    assert isinstance(executor, ci.InterpreterPoolCpuTaskExecutor)

    assert (
        "cpu_task_executor.selections",
        {"executor": "inline", "reason": "feature_flag_disabled"},
    ) in metrics.counters
    assert (
        "cpu_task_executor.selections",
        {"executor": "inline", "reason": "interpreter_pool_unavailable"},
    ) in metrics.counters
    assert (
        "cpu_task_executor.selections",
        {"executor": "interpreter_pool", "reason": "enabled"},
    ) in metrics.counters
    _shutdown_if_supported(disabled_executor)
    _shutdown_if_supported(unsupported_executor)
    executor.shutdown()


@pytest.mark.asyncio
async def test_builder_passes_metrics_to_interpreter_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Builder-provided metrics receive interpreter executor lifecycle signals."""
    metrics = _FakeCpuTaskExecutorMetrics()
    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        lambda max_workers: cf.ThreadPoolExecutor(max_workers=max_workers),
    )
    executor = ci.build_cpu_task_executor_from_environment(
        {"EPISODIC_USE_INTERPRETER_POOL": "1"},
        metrics=metrics,
        _capability_check=lambda: True,
    )
    assert isinstance(executor, ci.InterpreterPoolCpuTaskExecutor)

    try:
        assert await executor.map_ordered(_square, (2,)) == [4]
    finally:
        executor.shutdown()

    assert (
        "interpreter_pool.map.items",
        1.0,
        {"outcome": "success"},
    ) in metrics.observations
