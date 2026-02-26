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
    *,
    env_flag: str,
    mock_support: bool | None,
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
