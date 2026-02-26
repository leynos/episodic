"""Unit tests for interpreter-backed CPU task execution adapters."""

from __future__ import annotations

import concurrent.futures as cf

import pytest

import episodic.concurrent_interpreters as ci


def _square(value: int) -> int:
    return value * value


def _explode_on_three(value: int) -> int:
    if value == 3:
        msg = "bad value: 3"
        raise ValueError(msg)
    return value


@pytest.mark.asyncio
async def test_inline_executor_maps_values_in_order() -> None:
    """Inline execution preserves deterministic input ordering."""
    executor = ci.InlineCpuTaskExecutor()

    results = await executor.map_ordered(_square, (2, 1, 3))

    assert results == [4, 1, 9], (
        "Expected inline executor to keep map output aligned with input order."
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
    monkeypatch: pytest.MonkeyPatch,
    env_flag: str,
    mock_support: bool | None,  # noqa: FBT001
    expected_type: type[object],
) -> None:
    """Builder picks the expected executor for each environment combination."""
    monkeypatch.setenv("EPISODIC_USE_INTERPRETER_POOL", env_flag)
    if mock_support is not None:
        monkeypatch.setattr(ci, "interpreter_pool_supported", lambda: mock_support)

    executor = ci.build_cpu_task_executor_from_environment()

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

    monkeypatch.setenv("EPISODIC_USE_INTERPRETER_POOL", "1")
    monkeypatch.setenv("EPISODIC_INTERPRETER_POOL_MAX_WORKERS", env_value)
    monkeypatch.setattr(ci, "interpreter_pool_supported", lambda: True)
    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        fake_create_interpreter_pool_executor,
    )

    executor = ci.build_cpu_task_executor_from_environment()
    assert isinstance(executor, ci.InterpreterPoolCpuTaskExecutor)

    try:
        results = await executor.map_ordered(_square, (1,))
    finally:
        executor.shutdown()

    assert results == [1], "Expected interpreter-backed mapping to run successfully."
    assert captured["max_workers"] == expected_max_workers, (
        "Expected max_workers to be parsed from environment safely."
    )
