"""Lifecycle and observability tests for interpreter CPU task executors."""

from __future__ import annotations

import asyncio
import concurrent.futures as cf
import dataclasses as dc
import threading
import typing as typ
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import episodic.concurrent_interpreters as ci

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def _square(value: int) -> int:
    """Return the square of a generated executor input."""
    return value * value


class _BlockingMapExecutor(cf.Executor):
    """Executor test double that exposes map/shutdown ordering."""

    def __init__(self) -> None:
        self.map_started = threading.Event()
        self.release_map = threading.Event()
        self.shutdown_called = threading.Event()

    def map(
        self,
        fn: cabc.Callable[..., int],
        *iterables: cabc.Iterable[typ.Any],
        **kwargs: object,
    ) -> cabc.Iterator[int]:
        """Block mapped work until the test releases it."""
        del kwargs
        items = tuple(typ.cast("cabc.Iterable[int]", iterables[0]))
        self.map_started.set()
        if not self.release_map.wait(timeout=5):
            msg = "Timed out waiting for test to release executor.map()."
            raise TimeoutError(msg)
        return iter(fn(item) for item in items)

    def shutdown(
        self,
        wait: bool = True,  # noqa: FBT001, FBT002
        *,
        cancel_futures: bool = False,
    ) -> None:
        """Record that shutdown reached the underlying executor."""
        del wait, cancel_futures
        self.shutdown_called.set()


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
        """Record an observed measurement."""
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


@settings(max_examples=25, deadline=None)
@given(
    item_count=st.integers(min_value=1, max_value=5),
    release_before_shutdown=st.booleans(),
)
def test_interpreter_executor_shutdown_race_preserves_state(
    item_count: int,
    release_before_shutdown: bool,  # noqa: FBT001
) -> None:
    """Generated map/shutdown races leave the executor terminal after shutdown."""

    async def exercise_race() -> None:
        blocking_executor = _BlockingMapExecutor()
        create_executor = mock.patch.object(
            ci,
            "_create_interpreter_pool_executor",
            side_effect=lambda max_workers: blocking_executor,
        )
        with create_executor:
            executor = ci.InterpreterPoolCpuTaskExecutor()
            items = tuple(range(item_count))
            map_task = asyncio.create_task(executor.map_ordered(_square, items))

            map_started = await asyncio.to_thread(
                blocking_executor.map_started.wait,
                5,
            )
            assert map_started, "Expected map_ordered() to reach executor.map()."

            if release_before_shutdown:
                blocking_executor.release_map.set()
                assert await map_task == [_square(item) for item in items]
                executor.shutdown()
            else:
                shutdown_task = asyncio.create_task(
                    asyncio.to_thread(executor.shutdown),
                )
                await asyncio.sleep(0)
                assert not blocking_executor.shutdown_called.is_set()
                blocking_executor.release_map.set()
                assert await map_task == [_square(item) for item in items]
                await shutdown_task

            assert blocking_executor.shutdown_called.is_set()
            with pytest.raises(RuntimeError, match="has been shut down"):
                await executor.map_ordered(_square, items)

    asyncio.run(exercise_race())


@settings(max_examples=40, deadline=None)
@given(
    operations=st.lists(
        st.sampled_from(["map_empty", "map_values", "shutdown"]),
        min_size=1,
        max_size=8,
    ),
    item_count=st.integers(min_value=1, max_value=5),
)
def test_interpreter_executor_lifecycle_state_sequences(
    operations: list[str],
    item_count: int,
) -> None:
    """Generated lifecycle sequences enforce terminal shutdown semantics."""
    created_pools = 0

    def fake_create_interpreter_pool_executor(max_workers: int | None) -> cf.Executor:
        nonlocal created_pools
        created_pools += 1
        return cf.ThreadPoolExecutor(max_workers=max_workers)

    create_executor = mock.patch.object(
        ci,
        "_create_interpreter_pool_executor",
        side_effect=fake_create_interpreter_pool_executor,
    )
    with create_executor:
        executor = ci.InterpreterPoolCpuTaskExecutor(max_workers=2)
        is_shutdown = False
        expected_created_pools = 0

        for operation in operations:
            if operation == "shutdown":
                executor.shutdown()
                is_shutdown = True
                continue

            items = () if operation == "map_empty" else tuple(range(item_count))
            if is_shutdown:
                with pytest.raises(RuntimeError, match="has been shut down"):
                    asyncio.run(executor.map_ordered(_square, items))
                continue

            results = asyncio.run(executor.map_ordered(_square, items))
            assert results == [_square(item) for item in items]
            if items and expected_created_pools == 0:
                expected_created_pools = 1

        executor.shutdown()
    assert created_pools == expected_created_pools


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
        "interpreter_pool.shutdown.latency_ms",
        pytest.approx(25.0),
        {"outcome": "success"},
    ) in metrics.observations
    assert "Created interpreter-pool executor" in logger.messages
    assert "Shut down interpreter-pool executor" in logger.messages
