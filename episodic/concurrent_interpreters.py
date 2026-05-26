"""Execution adapters for optional Python 3.14 interpreter pools.

This module provides a small CPU-task execution port plus two adapters:
inline execution and interpreter-pool execution. The interpreter adapter is
feature-flagged and capability-gated so callers can opt in safely.
"""

from __future__ import annotations

import asyncio
import collections.abc as cabc
import concurrent.futures as cf
import dataclasses as dc
import logging
import os
import threading
import time
import typing as typ

_InputT = typ.TypeVar("_InputT")
_OutputT = typ.TypeVar("_OutputT")
type InterpreterPoolCapability = cabc.Callable[[], bool]

_INTERPRETER_POOL_FEATURE_FLAG = "EPISODIC_USE_INTERPRETER_POOL"
_INTERPRETER_POOL_MAX_WORKERS_ENV = "EPISODIC_INTERPRETER_POOL_MAX_WORKERS"
_METRIC_EXECUTOR_SELECTIONS = "cpu_task_executor.selections"
_METRIC_POOL_CREATIONS = "interpreter_pool.creations"
_METRIC_MAP_CALLS = "interpreter_pool.map.calls"
_METRIC_MAP_ITEMS = "interpreter_pool.map.items"
_METRIC_SHUTDOWN_LATENCY_MS = "interpreter_pool.shutdown.latency_ms"
_TRUTHY_VALUES = frozenset({"1", "on", "true", "yes"})
_log = logging.getLogger(__name__)


class CpuTaskExecutorMetricsPort(typ.Protocol):
    """Bounded-cardinality metrics sink for CPU task executors."""

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Increment a bounded-cardinality counter."""

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Observe a latency measurement in milliseconds."""

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Observe a non-latency numeric measurement."""


class CpuTaskExecutorClockPort(typ.Protocol):
    """Monotonic clock used to measure executor lifecycle timings."""

    def monotonic_seconds(self) -> float:
        """Return a monotonic timestamp in seconds."""


@dc.dataclass(frozen=True, slots=True)
class _NoopCpuTaskExecutorMetrics:
    """Default metrics sink used when no backend is wired."""

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Ignore counter increments."""

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Ignore latency observations."""

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Ignore non-latency observations."""


@dc.dataclass(frozen=True, slots=True)
class _PerfCounterCpuTaskExecutorClock:
    """Production executor clock backed by Python's monotonic perf counter."""

    read_seconds: cabc.Callable[[], float] = time.perf_counter

    def monotonic_seconds(self) -> float:
        """Return the current monotonic timestamp in seconds."""
        return self.read_seconds()


_CPU_TASK_EXECUTOR_METRICS = _NoopCpuTaskExecutorMetrics()


class CpuTaskExecutor(typ.Protocol):
    """Port for deterministic mapping of CPU-bound tasks."""

    async def map_ordered(
        self,
        task: cabc.Callable[[_InputT], _OutputT],
        items: tuple[_InputT, ...],
    ) -> list[_OutputT]:
        """Apply ``task`` to ``items`` and preserve input ordering."""
        raise NotImplementedError


def _parse_optional_positive_int(value: str | None) -> int | None:
    """Parse a positive integer environment value.

    Invalid values return ``None`` so callers can safely fall back to
    runtime defaults.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def _flag_enabled(raw_value: str | None) -> bool:
    """Return True when an environment toggle is truthy."""
    if raw_value is None:
        return False
    return raw_value.strip().lower() in _TRUTHY_VALUES


def interpreter_pool_supported() -> bool:
    """Return True when interpreter pools are available in this runtime."""
    return hasattr(cf, "InterpreterPoolExecutor")


def _create_interpreter_pool_executor(max_workers: int | None) -> cf.Executor:
    """Build an ``InterpreterPoolExecutor`` instance."""
    try:
        interpreter_pool_executor = cf.InterpreterPoolExecutor
    except AttributeError as err:
        msg = "InterpreterPoolExecutor is not available in this Python runtime."
        raise RuntimeError(msg) from err
    return interpreter_pool_executor(max_workers=max_workers)


class InlineCpuTaskExecutor(CpuTaskExecutor):
    """Baseline CPU-task adapter that runs work inline in the caller process."""

    @typ.override
    async def map_ordered(
        self,
        task: cabc.Callable[[_InputT], _OutputT],
        items: tuple[_InputT, ...],
    ) -> list[_OutputT]:
        """Apply ``task`` sequentially and preserve input ordering."""
        return [task(item) for item in items]


class InterpreterPoolCpuTaskExecutor(CpuTaskExecutor):
    """CPU-task adapter backed by ``InterpreterPoolExecutor``.

    Parameters
    ----------
    max_workers : int | None
        Optional explicit worker count for interpreter pool creation.

    Notes
    -----
    Each instance owns its interpreter pool. Create the executor at the
    boundary that owns the CPU fan-out operation, reuse it for the related
    ``map_ordered()`` calls, and call ``shutdown()`` when that operation or
    worker-scoped owner is finished. Lazy pool creation is protected by a
    lock, but callers should still avoid sharing one executor as mutable global
    state across unrelated task flows.
    """

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        metrics: CpuTaskExecutorMetricsPort | None = None,
        clock: CpuTaskExecutorClockPort | None = None,
    ) -> None:
        self._max_workers = max_workers
        self._executor: cf.Executor | None = None
        self._executor_lock = threading.RLock()
        self._is_shutdown = False
        self._metrics = (
            metrics if metrics is not None else _NoopCpuTaskExecutorMetrics()
        )
        self._clock = clock if clock is not None else _PerfCounterCpuTaskExecutorClock()

    def _get_executor(self) -> cf.Executor:
        """Return the interpreter pool, creating it on first use."""
        with self._executor_lock:
            if self._is_shutdown:
                msg = "InterpreterPoolCpuTaskExecutor has been shut down."
                raise RuntimeError(msg)
            if self._executor is None:
                outcome = "success"
                try:
                    self._executor = _create_interpreter_pool_executor(
                        self._max_workers,
                    )
                except Exception:
                    outcome = "error"
                    _log.exception(
                        "Failed to create interpreter-pool executor",
                        extra={"max_workers": self._max_workers},
                    )
                    raise
                finally:
                    self._metrics.increment_counter(
                        _METRIC_POOL_CREATIONS,
                        labels={"outcome": outcome},
                    )
                _log.info(
                    "Created interpreter-pool executor",
                    extra={"max_workers": self._max_workers},
                )
            return self._executor

    def shutdown(self) -> None:
        """Shut down the interpreter pool atomically."""
        with self._executor_lock:
            started = self._clock.monotonic_seconds()
            self._is_shutdown = True
            executor = self._executor
            self._executor = None
            if executor is not None:
                outcome = "success"
                try:
                    executor.shutdown(wait=True)
                except Exception:
                    outcome = "error"
                    _log.exception(
                        "Interpreter-pool executor shutdown failed",
                        extra={"max_workers": self._max_workers},
                    )
                    raise
                finally:
                    self._metrics.observe_latency_ms(
                        _METRIC_SHUTDOWN_LATENCY_MS,
                        (self._clock.monotonic_seconds() - started) * 1000,
                        labels={"outcome": outcome},
                    )
                _log.info(
                    "Shut down interpreter-pool executor",
                    extra={"max_workers": self._max_workers},
                )

    @typ.override
    async def map_ordered(
        self,
        task: cabc.Callable[[_InputT], _OutputT],
        items: tuple[_InputT, ...],
    ) -> list[_OutputT]:
        """Dispatch ``task`` across interpreter workers and preserve order."""
        with self._executor_lock:
            if self._is_shutdown:
                msg = "InterpreterPoolCpuTaskExecutor has been shut down."
                raise RuntimeError(msg)
            if not items:
                return []

        def map_ordered_sync() -> list[_OutputT]:
            with self._executor_lock:
                executor = self._get_executor()
                try:
                    result = list(executor.map(task, items))
                except Exception:
                    self._metrics.increment_counter(
                        _METRIC_MAP_CALLS,
                        labels={"outcome": "error"},
                    )
                    _log.exception(
                        "Interpreter-pool executor map failed",
                        extra={
                            "item_count": len(items),
                            "max_workers": self._max_workers,
                        },
                    )
                    raise
                self._metrics.increment_counter(
                    _METRIC_MAP_CALLS,
                    labels={"outcome": "success"},
                )
                self._metrics.observe_value(
                    _METRIC_MAP_ITEMS,
                    float(len(items)),
                    labels={"outcome": "success"},
                )
                return result

        return await asyncio.to_thread(map_ordered_sync)


def build_cpu_task_executor_from_environment(
    environ: cabc.Mapping[str, str] | None = None,
    *,
    capability_check: InterpreterPoolCapability = interpreter_pool_supported,
    metrics: CpuTaskExecutorMetricsPort | None = None,
) -> CpuTaskExecutor:
    """Select CPU-task adapter based on feature flag and runtime capability.

    Parameters
    ----------
    environ : collections.abc.Mapping[str, str] | None
        Environment mapping to inspect. ``None`` falls back to ``os.environ``
        for backwards-compatible composition-root usage.
    capability_check : collections.abc.Callable[[], bool]
        Runtime capability probe for interpreter-pool support. Tests and
        composition roots can inject this instead of monkeypatching module
        state.
    metrics : CpuTaskExecutorMetricsPort | None
        Metrics sink for executor selection and interpreter-pool lifecycle
        observations. ``None`` uses the module default no-op sink.

    The returned object is owned by the caller. Inline executors have no
    resources to release; interpreter-pool executors should be shut down by the
    task-level owner after the fan-out work completes, commonly with
    ``try/finally`` and ``getattr(executor, "shutdown", None)`` so the same
    code works for both adapters.
    """
    environ_ = os.environ if environ is None else environ
    metrics_ = metrics if metrics is not None else _CPU_TASK_EXECUTOR_METRICS
    if not _flag_enabled(environ_.get(_INTERPRETER_POOL_FEATURE_FLAG)):
        metrics_.increment_counter(
            _METRIC_EXECUTOR_SELECTIONS,
            labels={"executor": "inline", "reason": "feature_flag_disabled"},
        )
        _log.info(
            "Using inline CPU task executor",
            extra={"reason": "feature_flag_disabled"},
        )
        return InlineCpuTaskExecutor()
    if not capability_check():
        metrics_.increment_counter(
            _METRIC_EXECUTOR_SELECTIONS,
            labels={"executor": "inline", "reason": "interpreter_pool_unavailable"},
        )
        _log.info(
            "Using inline CPU task executor",
            extra={"reason": "interpreter_pool_unavailable"},
        )
        return InlineCpuTaskExecutor()
    max_workers = _parse_optional_positive_int(
        environ_.get(_INTERPRETER_POOL_MAX_WORKERS_ENV),
    )
    metrics_.increment_counter(
        _METRIC_EXECUTOR_SELECTIONS,
        labels={"executor": "interpreter_pool", "reason": "enabled"},
    )
    _log.info(
        "Using interpreter-pool CPU task executor",
        extra={"max_workers": max_workers},
    )
    return InterpreterPoolCpuTaskExecutor(max_workers=max_workers, metrics=metrics_)


__all__ = [
    "CpuTaskExecutor",
    "CpuTaskExecutorClockPort",
    "CpuTaskExecutorMetricsPort",
    "InlineCpuTaskExecutor",
    "InterpreterPoolCapability",
    "InterpreterPoolCpuTaskExecutor",
    "build_cpu_task_executor_from_environment",
    "interpreter_pool_supported",
]
