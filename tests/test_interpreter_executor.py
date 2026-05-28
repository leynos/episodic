"""Unit tests for interpreter-backed CPU task execution adapters."""

from __future__ import annotations

import asyncio
import concurrent.futures as cf
import operator
import typing as typ
from unittest import mock

import pytest
from hypothesis import given
from hypothesis import strategies as st

import episodic.concurrent_interpreters as ci
from tests.conftest import BlockingMapExecutor as _BlockingMapExecutor
from tests.conftest import square_executor_value as _square

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def _explode_on_three(value: int) -> int:
    """Raise on a sentinel value to prove executor errors propagate."""
    if value == 3:
        msg = "bad value: 3"
        raise ValueError(msg)
    return value


def _affine(value: int) -> int:
    """Apply a non-symmetric transform for ordering property tests."""
    return (value * 3) - 7


_ORDERED_MAP_TASKS: dict[str, cabc.Callable[[int], int]] = {
    "affine": _affine,
    "negate": typ.cast("cabc.Callable[[int], int]", operator.neg),
    "square": _square,
}


@pytest.mark.asyncio
async def test_inline_executor_maps_values_in_order() -> None:
    """Inline execution preserves deterministic input ordering."""
    executor = ci.InlineCpuTaskExecutor()

    results = await executor.map_ordered(_square, (2, 1, 3))

    assert results == [4, 1, 9], (
        "Expected inline executor to keep map output aligned with input order."
    )


@given(
    items=st.lists(st.integers(min_value=-100, max_value=100), max_size=25),
    task_name=st.sampled_from(sorted(_ORDERED_MAP_TASKS)),
)
def test_inline_executor_preserves_order_for_arbitrary_inputs(
    items: list[int],
    task_name: str,
) -> None:
    """Inline execution preserves map ordering for generated inputs."""
    task = _ORDERED_MAP_TASKS[task_name]
    executor = ci.InlineCpuTaskExecutor()

    results = asyncio.run(executor.map_ordered(task, tuple(items)))

    assert results == [task(item) for item in items], (
        "Expected inline executor output to align with generated input order."
    )


@pytest.mark.asyncio
async def test_interpreter_executor_maps_values_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interpreter-backed execution preserves deterministic input ordering."""
    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        lambda max_workers: cf.ThreadPoolExecutor(max_workers=max_workers),
    )
    executor = ci.InterpreterPoolCpuTaskExecutor()

    try:
        results = await executor.map_ordered(_square, (2, 1, 3))
    finally:
        executor.shutdown()

    assert results == [4, 1, 9], (
        "Expected interpreter-backed executor to keep output aligned with input order."
    )


@given(
    items=st.lists(st.integers(min_value=-100, max_value=100), max_size=25),
    task_name=st.sampled_from(sorted(_ORDERED_MAP_TASKS)),
)
def test_interpreter_executor_preserves_order_for_arbitrary_inputs(
    items: list[int],
    task_name: str,
) -> None:
    """Interpreter-backed execution preserves map ordering for generated inputs."""
    create_executor = mock.patch.object(
        ci,
        "_create_interpreter_pool_executor",
        side_effect=lambda max_workers: cf.ThreadPoolExecutor(max_workers=max_workers),
    )
    task = _ORDERED_MAP_TASKS[task_name]
    with create_executor:
        executor = ci.InterpreterPoolCpuTaskExecutor(max_workers=3)

        try:
            results = asyncio.run(executor.map_ordered(task, tuple(items)))
        finally:
            executor.shutdown()

    assert results == [task(item) for item in items], (
        "Expected interpreter-backed executor output to align with input order."
    )


@pytest.mark.asyncio
async def test_interpreter_executor_propagates_worker_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errors raised by mapped tasks propagate to caller."""
    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        lambda max_workers: cf.ThreadPoolExecutor(max_workers=max_workers),
    )
    executor = ci.InterpreterPoolCpuTaskExecutor()

    try:
        with pytest.raises(ValueError, match="bad value: 3"):
            await executor.map_ordered(_explode_on_three, (1, 2, 3, 4))
    finally:
        executor.shutdown()


@pytest.mark.asyncio
async def test_interpreter_executor_shutdown_waits_for_active_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent shutdown waits until an active map operation releases the pool."""
    blocking_executor = _BlockingMapExecutor()
    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        lambda max_workers: blocking_executor,
    )
    executor = ci.InterpreterPoolCpuTaskExecutor()
    map_task = asyncio.create_task(executor.map_ordered(_square, (2, 4)))

    map_started = await asyncio.to_thread(blocking_executor.map_started.wait, 5)
    assert map_started, "Expected map_ordered() to reach the underlying executor."

    shutdown_task = asyncio.create_task(asyncio.to_thread(executor.shutdown))
    await asyncio.sleep(0.05)
    assert not blocking_executor.shutdown_called.is_set(), (
        "Expected shutdown() to wait for the active map_ordered() call."
    )

    blocking_executor.release_map.set()
    assert await map_task == [4, 16]
    await shutdown_task
    assert blocking_executor.shutdown_called.is_set(), (
        "Expected shutdown() to reach the pool after map_ordered() completes."
    )


@pytest.mark.asyncio
async def test_interpreter_executor_map_after_shutdown_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling map_ordered after shutdown raises instead of creating a pool."""
    created_pools: list[cf.ThreadPoolExecutor] = []

    def fake_create_interpreter_pool_executor(
        max_workers: int | None,
    ) -> cf.ThreadPoolExecutor:
        pool = cf.ThreadPoolExecutor(max_workers=max_workers)
        created_pools.append(pool)
        return pool

    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        fake_create_interpreter_pool_executor,
    )
    executor = ci.InterpreterPoolCpuTaskExecutor(max_workers=1)
    executor.shutdown()

    with pytest.raises(RuntimeError, match="has been shut down"):
        await executor.map_ordered(_square, (3,))

    assert not created_pools, (
        "Expected post-shutdown mapping to avoid creating a new pool."
    )


def test_interpreter_executor_shutdown_is_idempotent() -> None:
    """Calling shutdown twice is a no-op after the first shutdown."""
    executor = ci.InterpreterPoolCpuTaskExecutor()

    executor.shutdown()
    executor.shutdown()
    assert executor._is_shutdown is True


@pytest.mark.asyncio
async def test_inline_executor_handles_empty_input() -> None:
    """Inline adapter returns an empty list for empty workloads."""
    executor = ci.InlineCpuTaskExecutor()

    results = await executor.map_ordered(_square, ())

    assert results == [], "Expected empty workloads to return an empty result list."


@pytest.mark.asyncio
async def test_interpreter_executor_handles_empty_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interpreter-backed adapter returns [] for empty workloads without errors."""
    created_pools = {"count": 0}

    def fake_create_interpreter_pool_executor(max_workers: int | None) -> cf.Executor:
        created_pools["count"] += 1
        return cf.ThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        fake_create_interpreter_pool_executor,
    )
    executor = ci.InterpreterPoolCpuTaskExecutor()

    try:
        results = await executor.map_ordered(_square, ())
    finally:
        executor.shutdown()

    assert results == [], "Expected empty workloads to return an empty result list."
    assert created_pools["count"] == 0, (
        "Expected no interpreter pool to be created for empty workloads."
    )


@pytest.mark.parametrize(
    ("env_flag", "mock_support", "expected_type"),
    [
        (
            "0",
            None,
            ci.InlineCpuTaskExecutor,
        ),
        (
            "1",
            False,
            ci.InlineCpuTaskExecutor,
        ),
        (
            "1",
            True,
            ci.InterpreterPoolCpuTaskExecutor,
        ),
    ],
    ids=[
        "feature_flag_disabled",
        "interpreters_unavailable",
        "enabled_and_supported",
    ],
)
def test_builder_selects_executor_based_on_environment(
    env_flag: str,
    mock_support: bool | None,  # noqa: FBT001
    expected_type: type[object],
) -> None:
    """Builder picks the expected executor for each environment combination."""
    environ = {"EPISODIC_USE_INTERPRETER_POOL": env_flag}
    capability_check = ci.interpreter_pool_supported
    if mock_support is not None:

        def capability_check() -> bool:
            return mock_support

    executor = ci._build_cpu_task_executor_from_environment(
        environ,
        metrics=ci._CPU_TASK_EXECUTOR_METRICS,
        _capability_check=capability_check,
    )

    assert isinstance(executor, expected_type), (
        f"Expected {expected_type.__name__} based on environment configuration."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("env_value", "expected_max_workers"),
    [
        ("4", 4),
        ("abc", None),
        ("0", None),
        ("-1", None),
    ],
)
async def test_builder_parses_max_workers_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
    expected_max_workers: int | None,
) -> None:
    """Builder converts max-workers env values into safe executor configuration."""
    captured: dict[str, int | None] = {}

    def fake_create_interpreter_pool_executor(max_workers: int | None) -> cf.Executor:
        captured["max_workers"] = max_workers
        return cf.ThreadPoolExecutor(max_workers=1)

    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        fake_create_interpreter_pool_executor,
    )
    environ = {
        "EPISODIC_USE_INTERPRETER_POOL": "1",
        "EPISODIC_INTERPRETER_POOL_MAX_WORKERS": env_value,
    }

    executor = ci._build_cpu_task_executor_from_environment(
        environ,
        metrics=ci._CPU_TASK_EXECUTOR_METRICS,
        _capability_check=lambda: True,
    )
    assert isinstance(executor, ci.InterpreterPoolCpuTaskExecutor)

    try:
        results = await executor.map_ordered(_square, (1,))
    finally:
        executor.shutdown()

    assert results == [1], "Expected interpreter-backed mapping to run successfully."
    assert captured["max_workers"] == expected_max_workers, (
        "Expected max_workers to be parsed from environment safely."
    )
