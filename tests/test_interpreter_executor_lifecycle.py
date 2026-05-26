"""Lifecycle tests for interpreter CPU task executors."""

from __future__ import annotations

import asyncio
import concurrent.futures as cf
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import episodic.concurrent_interpreters as ci
from tests.conftest import BlockingMapExecutor as _BlockingMapExecutor
from tests.conftest import square_executor_value as _square


def _raise_on_negative(value: int) -> int:
    """Raise on negative values for generated failure-state tests."""
    if value < 0:
        msg = "negative values are rejected"
        raise ValueError(msg)
    return value


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


@settings(max_examples=20, deadline=None)
@given(
    first_count=st.integers(min_value=1, max_value=4),
    second_count=st.integers(min_value=1, max_value=4),
    release_order=st.sampled_from(["first", "second"]),
)
def test_interpreter_executor_concurrent_maps_then_shutdown_are_terminal(
    first_count: int,
    second_count: int,
    release_order: str,
) -> None:
    """Generated multi-map interleavings serialise before terminal shutdown."""

    async def exercise_interleaving() -> None:
        create_executor = mock.patch.object(
            ci,
            "_create_interpreter_pool_executor",
            side_effect=lambda max_workers: cf.ThreadPoolExecutor(
                max_workers=max_workers,
            ),
        )
        with create_executor:
            executor = ci.InterpreterPoolCpuTaskExecutor(max_workers=2)
            first_items = tuple(range(first_count))
            second_items = tuple(range(second_count))
            first_task = asyncio.create_task(executor.map_ordered(_square, first_items))
            second_task = asyncio.create_task(
                executor.map_ordered(_square, second_items),
            )

            if release_order == "second":
                second_result, first_result = await asyncio.gather(
                    second_task,
                    first_task,
                )
            else:
                first_result, second_result = await asyncio.gather(
                    first_task,
                    second_task,
                )

            assert first_result == [_square(item) for item in first_items]
            assert second_result == [_square(item) for item in second_items]

            executor.shutdown()
            with pytest.raises(RuntimeError, match="has been shut down"):
                await executor.map_ordered(_square, first_items)

    asyncio.run(exercise_interleaving())


@settings(max_examples=30, deadline=None)
@given(
    operations=st.lists(
        st.sampled_from(["map_success", "map_error", "shutdown"]),
        min_size=1,
        max_size=6,
    ),
)
def test_interpreter_executor_failure_sequences_remain_terminal(
    operations: list[str],
) -> None:
    """Generated map-failure sequences preserve shutdown as terminal state."""
    create_executor = mock.patch.object(
        ci,
        "_create_interpreter_pool_executor",
        side_effect=lambda max_workers: cf.ThreadPoolExecutor(max_workers=max_workers),
    )
    with create_executor:
        executor = ci.InterpreterPoolCpuTaskExecutor(max_workers=2)
        is_shutdown = False

        for operation in operations:
            if operation == "shutdown":
                executor.shutdown()
                is_shutdown = True
                continue

            items = (-1,) if operation == "map_error" else (1, 2)
            if is_shutdown:
                with pytest.raises(RuntimeError, match="has been shut down"):
                    asyncio.run(executor.map_ordered(_raise_on_negative, items))
                continue
            if operation == "map_error":
                with pytest.raises(ValueError, match="negative values are rejected"):
                    asyncio.run(executor.map_ordered(_raise_on_negative, items))
            else:
                assert asyncio.run(executor.map_ordered(_raise_on_negative, items)) == [
                    1,
                    2,
                ]

        executor.shutdown()
        with pytest.raises(RuntimeError, match="has been shut down"):
            asyncio.run(executor.map_ordered(_raise_on_negative, (1,)))
