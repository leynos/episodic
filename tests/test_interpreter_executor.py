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
async def test_interpreter_executor_propagates_worker_exception() -> None:
    """Errors raised by mapped tasks propagate to caller."""
    executor = ci.InterpreterPoolCpuTaskExecutor(
        executor_factory=lambda max_workers: cf.ThreadPoolExecutor(
            max_workers=max_workers,
        ),
    )

    with pytest.raises(ValueError, match="bad value: 3"):
        await executor.map_ordered(_explode_on_three, (1, 2, 3, 4))


def test_builder_returns_inline_when_feature_flag_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled feature flag forces baseline inline execution."""
    monkeypatch.setenv("EPISODIC_USE_INTERPRETER_POOL", "0")

    executor = ci.build_cpu_task_executor_from_environment()

    assert isinstance(executor, ci.InlineCpuTaskExecutor), (
        "Expected inline executor when interpreter pool feature flag is disabled."
    )


def test_builder_returns_inline_when_interpreters_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported runtimes fall back to inline execution."""
    monkeypatch.setenv("EPISODIC_USE_INTERPRETER_POOL", "1")
    monkeypatch.setattr(ci, "interpreter_pool_supported", lambda: False)

    executor = ci.build_cpu_task_executor_from_environment()

    assert isinstance(executor, ci.InlineCpuTaskExecutor), (
        "Expected inline executor when runtime lacks interpreter-pool support."
    )


def test_builder_selects_interpreter_executor_when_enabled_and_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled feature flag plus support selects interpreter executor."""
    monkeypatch.setenv("EPISODIC_USE_INTERPRETER_POOL", "1")
    monkeypatch.setattr(ci, "interpreter_pool_supported", lambda: True)

    executor = ci.build_cpu_task_executor_from_environment()

    assert isinstance(executor, ci.InterpreterPoolCpuTaskExecutor), (
        "Expected interpreter executor when feature flag is enabled and supported."
    )
