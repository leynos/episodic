"""Tests for asyncio task-factory keyword propagation utilities."""

import asyncio
import contextvars as cv
import functools
import typing as typ

import pytest

from episodic.asyncio_tasks import (
    TASK_METADATA_KWARG,
    TaskCreateKwargs,
    TaskMetadata,
    create_task,
    create_task_in_group,
)
from tests.fixtures.async_task_factory import (
    recording_task_factory,
    select_captured_task_kwargs,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_UNKNOWN_TASK_KWARGS: typ.Final = typ.cast(
    "TaskCreateKwargs", {"unsupported_kwarg": "value"}
)


@pytest.mark.asyncio
async def test_create_task_forwards_task_factory_kwargs() -> None:
    """`create_task` forwards stdlib and custom kwargs to task factories."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return "done"

    metadata: TaskMetadata = {
        "operation_name": "tests.create_task",
        "correlation_id": "corr-123",
        "priority_hint": 3,
    }
    context = cv.copy_context()

    with recording_task_factory() as captured:
        task = create_task(
            _job(),
            name="create-task-test",
            context=context,
            eager_start=True,
            metadata=metadata,
        )
        result = await task

    assert result == "done", f"expected result == 'done', got {result!r}"
    kwargs = select_captured_task_kwargs(captured, "create-task-test")
    assert kwargs["name"] == "create-task-test", (
        f"expected task name 'create-task-test', got {kwargs['name']!r}"
    )
    assert kwargs["context"] is context, (
        f"expected task context object {context!r}, got {kwargs['context']!r}"
    )
    assert kwargs["eager_start"] is True, (
        f"expected eager_start True, got {kwargs['eager_start']!r}"
    )
    assert kwargs[TASK_METADATA_KWARG] == metadata, (
        f"expected metadata {metadata!r}, got {kwargs[TASK_METADATA_KWARG]!r}"
    )


@pytest.mark.asyncio
async def test_create_task_in_group_forwards_task_factory_kwargs() -> None:
    """`create_task_in_group` forwards kwargs to task factories."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return "group-done"

    metadata: TaskMetadata = {
        "operation_name": "tests.task_group",
        "correlation_id": "group-456",
    }

    with recording_task_factory() as captured:
        async with asyncio.TaskGroup() as group:
            task = create_task_in_group(
                group,
                _job(),
                name="task-group-test",
                eager_start=False,
                metadata=metadata,
            )

    task_result = task.result()
    assert task_result == "group-done", (
        f"expected task group result 'group-done', got {task_result!r}"
    )
    kwargs = select_captured_task_kwargs(captured, "task-group-test")
    assert kwargs["name"] == "task-group-test", (
        f"expected task name 'task-group-test', got {kwargs['name']!r}"
    )
    assert kwargs["eager_start"] is False, (
        f"expected eager_start False, got {kwargs['eager_start']!r}"
    )
    assert kwargs[TASK_METADATA_KWARG] == metadata, (
        f"expected metadata {metadata!r}, got {kwargs[TASK_METADATA_KWARG]!r}"
    )


def test_create_task_rejects_unsupported_metadata_key() -> None:
    """Unsupported metadata keys are rejected with a clear error."""
    coro: cabc.Coroutine[object, object, object] | None = None
    try:
        with pytest.raises(ValueError, match="Unsupported task metadata keys"):
            create_task(
                coro := asyncio.sleep(0),
                metadata=typ.cast("TaskMetadata", {"unsupported_key": "nope"}),
            )
    finally:
        if coro is not None:
            coro.close()


def test_create_task_rejects_unsupported_metadata_keys_with_mixed_types() -> None:
    """Unsupported metadata-key formatting handles mixed key types safely."""
    coro = asyncio.sleep(0)
    try:
        with pytest.raises(
            ValueError,
            match=r"Unsupported task metadata keys: 'unsupported_key', 1",
        ):
            create_task(
                coro,
                metadata=typ.cast(
                    "TaskMetadata",
                    typ.cast("dict[str, object]", {1: "nope", "unsupported_key": "x"}),
                ),
            )
    finally:
        coro.close()


@pytest.mark.parametrize(
    "make_call",
    [
        functools.partial(create_task, **_UNKNOWN_TASK_KWARGS),
        lambda coro: create_task_in_group(
            asyncio.TaskGroup(), coro, **_UNKNOWN_TASK_KWARGS
        ),
    ],
    ids=["create_task", "create_task_in_group"],
)
def test_task_creation_rejects_unknown_task_kwargs(
    make_call: cabc.Callable[..., object],
) -> None:
    """Unknown task kwargs are rejected instead of being silently ignored."""
    coro = asyncio.sleep(0)
    try:
        with pytest.raises(TypeError, match="unsupported_kwarg"):
            make_call(coro)
    finally:
        coro.close()


@pytest.mark.parametrize(
    ("metadata", "expected_exception", "expected_pattern"),
    [
        (
            {"operation_name": 123},
            TypeError,
            "operation_name",
        ),
        (
            {"operation_name": ""},
            ValueError,
            "operation_name",
        ),
        (
            {"correlation_id": 123},
            TypeError,
            "correlation_id",
        ),
        (
            {"correlation_id": ""},
            ValueError,
            "correlation_id",
        ),
        (
            {"priority_hint": "high"},
            TypeError,
            "priority_hint",
        ),
        (
            {"priority_hint": True},
            TypeError,
            "priority_hint",
        ),
    ],
    ids=[
        "operation_name_non_string",
        "operation_name_empty",
        "correlation_id_non_string",
        "correlation_id_empty",
        "priority_hint_non_int",
        "priority_hint_bool",
    ],
)
def test_create_task_rejects_invalid_metadata_values(
    metadata: dict[str, object],
    expected_exception: type[Exception],
    expected_pattern: str,
) -> None:
    """Invalid metadata values raise typed validation errors."""
    coro = asyncio.sleep(0)
    try:
        with pytest.raises(expected_exception, match=expected_pattern):
            create_task(coro, metadata=typ.cast("TaskMetadata", metadata))
    finally:
        coro.close()


@pytest.mark.asyncio
async def test_create_task_ignores_metadata_without_custom_factory() -> None:
    """Custom metadata is ignored when the running loop has no task factory."""
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    loop.set_task_factory(None)
    try:

        async def _job() -> str:
            await asyncio.sleep(0)
            return "ok"

        task = create_task(
            _job(),
            metadata={"operation_name": "tests.no_factory"},
        )
        task_result = await task
        assert task_result == "ok", (
            f"expected task result 'ok' without custom factory, got {task_result!r}"
        )
    finally:
        loop.set_task_factory(previous_factory)


@pytest.mark.asyncio
async def test_create_task_empty_metadata_is_not_forwarded() -> None:
    """An empty metadata dictionary is treated as absent metadata."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return "done"

    with recording_task_factory() as captured:
        task = create_task(
            _job(),
            name="create-task-empty-metadata",
            metadata=typ.cast("TaskMetadata", {}),
        )
        result = await task

    assert result == "done", f"expected result == 'done', got {result!r}"
    kwargs = select_captured_task_kwargs(captured, "create-task-empty-metadata")
    assert kwargs["name"] == "create-task-empty-metadata", (
        f"expected task name 'create-task-empty-metadata', got {kwargs['name']!r}"
    )
    assert TASK_METADATA_KWARG not in kwargs, (
        f"expected no {TASK_METADATA_KWARG!r} in task kwargs, got {kwargs!r}"
    )


@pytest.mark.asyncio
async def test_create_task_partial_metadata_forwards_present_keys_only() -> None:
    """Partial metadata is forwarded without synthesizing missing keys."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return "done"

    metadata: TaskMetadata = {"operation_name": "tests.create_task.partial"}

    with recording_task_factory() as captured:
        task = create_task(
            _job(),
            name="create-task-partial-metadata",
            metadata=metadata,
        )
        result = await task

    assert result == "done", f"expected result == 'done', got {result!r}"
    kwargs = select_captured_task_kwargs(captured, "create-task-partial-metadata")
    forwarded_metadata = typ.cast("dict[str, object]", kwargs[TASK_METADATA_KWARG])
    assert forwarded_metadata["operation_name"] == "tests.create_task.partial", (
        "expected operation_name 'tests.create_task.partial', "
        f"got {forwarded_metadata['operation_name']!r}"
    )
    assert "correlation_id" not in forwarded_metadata, (
        "expected forwarded metadata to omit 'correlation_id', "
        f"got {forwarded_metadata!r}"
    )
    assert "priority_hint" not in forwarded_metadata, (
        "expected forwarded metadata to omit 'priority_hint', "
        f"got {forwarded_metadata!r}"
    )
