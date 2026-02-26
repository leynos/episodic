"""Execution adapters for optional Python 3.14 interpreter pools.

This module provides a small CPU-task execution port plus two adapters:
inline execution and interpreter-pool execution. The interpreter adapter is
feature-flagged and capability-gated so callers can opt in safely.
"""

from __future__ import annotations

import asyncio
import concurrent.futures as cf
import importlib.util
import os
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_InputT = typ.TypeVar("_InputT")
_OutputT = typ.TypeVar("_OutputT")

_INTERPRETER_POOL_FEATURE_FLAG = "EPISODIC_USE_INTERPRETER_POOL"
_INTERPRETER_POOL_MAX_WORKERS_ENV = "EPISODIC_INTERPRETER_POOL_MAX_WORKERS"
_TRUTHY_VALUES = frozenset({"1", "on", "true", "yes"})


class CpuTaskExecutor(typ.Protocol):
    """Port for deterministic mapping of CPU-bound tasks."""

    async def map_ordered(
        self,
        task: cabc.Callable[[_InputT], _OutputT],
        items: tuple[_InputT, ...],
    ) -> list[_OutputT]:
        """Apply ``task`` to ``items`` and preserve input ordering."""
        ...


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
    if importlib.util.find_spec("concurrent.interpreters") is None:
        return False
    return hasattr(cf, "InterpreterPoolExecutor")


def _create_interpreter_pool_executor(max_workers: int | None) -> cf.Executor:
    """Build an ``InterpreterPoolExecutor`` instance."""
    interpreter_pool_executor = getattr(cf, "InterpreterPoolExecutor", None)
    if interpreter_pool_executor is None:
        msg = "InterpreterPoolExecutor is not available in this Python runtime."
        raise RuntimeError(msg)
    return typ.cast("cf.Executor", interpreter_pool_executor(max_workers=max_workers))


class InlineCpuTaskExecutor:
    """Baseline CPU-task adapter that runs work inline in the caller process."""

    def __init__(self) -> None:
        self._execution_mode = "inline"

    async def map_ordered(
        self,
        task: cabc.Callable[[_InputT], _OutputT],
        items: tuple[_InputT, ...],
    ) -> list[_OutputT]:
        """Apply ``task`` sequentially and preserve input ordering."""
        # Keep this adapter instance-oriented so it cleanly satisfies the port.
        _ = self._execution_mode
        return [task(item) for item in items]


class InterpreterPoolCpuTaskExecutor:
    """CPU-task adapter backed by ``InterpreterPoolExecutor``.

    Parameters
    ----------
    max_workers : int | None
        Optional explicit worker count for interpreter pool creation.
    executor_factory : Callable[[int | None], concurrent.futures.Executor] | None
        Optional factory used to create a fresh executor per dispatch.
        Primarily useful for deterministic tests.
    """

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        executor_factory: cabc.Callable[[int | None], cf.Executor] | None = None,
    ) -> None:
        self._max_workers = max_workers
        self._executor_factory = (
            executor_factory
            if executor_factory is not None
            else _create_interpreter_pool_executor
        )

    def _map_ordered_sync(
        self,
        task: cabc.Callable[[_InputT], _OutputT],
        items: tuple[_InputT, ...],
    ) -> list[_OutputT]:
        with self._executor_factory(self._max_workers) as executor:
            return list(executor.map(task, items))

    async def map_ordered(
        self,
        task: cabc.Callable[[_InputT], _OutputT],
        items: tuple[_InputT, ...],
    ) -> list[_OutputT]:
        """Dispatch ``task`` across interpreter workers and preserve order."""
        mapped = await asyncio.to_thread(self._map_ordered_sync, task, items)
        return typ.cast("list[_OutputT]", mapped)


def build_cpu_task_executor_from_environment() -> CpuTaskExecutor:
    """Select CPU-task adapter based on feature flag and runtime capability."""
    if not _flag_enabled(os.getenv(_INTERPRETER_POOL_FEATURE_FLAG)):
        return InlineCpuTaskExecutor()
    if not interpreter_pool_supported():
        return InlineCpuTaskExecutor()
    max_workers = _parse_optional_positive_int(
        os.getenv(_INTERPRETER_POOL_MAX_WORKERS_ENV),
    )
    return InterpreterPoolCpuTaskExecutor(max_workers=max_workers)


__all__ = [
    "CpuTaskExecutor",
    "InlineCpuTaskExecutor",
    "InterpreterPoolCpuTaskExecutor",
    "build_cpu_task_executor_from_environment",
    "interpreter_pool_supported",
]
