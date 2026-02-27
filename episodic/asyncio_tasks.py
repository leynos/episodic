"""Utilities for metadata-aware asyncio task creation.

This module centralizes task creation so asynchronous orchestration can attach
consistent metadata for custom event-loop task factories while preserving safe
behaviour when no factory is installed.
"""

from __future__ import annotations

import asyncio
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import contextvars as cv

TASK_METADATA_KWARG = "episodic_task_metadata"
_TASK_METADATA_KEYS = frozenset({"operation_name", "correlation_id", "priority_hint"})


class TaskMetadata(typ.TypedDict, total=False):
    """Optional metadata attached to task-factory task creation kwargs."""

    operation_name: str
    correlation_id: str
    priority_hint: int


class TaskCreateKwargs(typ.TypedDict, total=False):
    """Supported kwargs for metadata-aware task creation helpers."""

    name: str | None
    context: cv.Context | None
    eager_start: bool | None
    metadata: TaskMetadata | None


_TASK_CREATE_KWARGS_KEYS = frozenset({"name", "context", "eager_start", "metadata"})


def _validate_string_metadata_field(
    metadata: TaskMetadata,
    field_name: str,
) -> str | None:
    """Validate one optional string metadata field."""
    value = metadata.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = (
            f"Task metadata {field_name!r} must be a string, "
            f"got {type(value).__name__!r}."
        )
        raise TypeError(msg)
    if not value:
        msg = f"Task metadata {field_name!r} must be a non-empty string."
        raise ValueError(msg)
    return value


def _validate_priority_hint_field(metadata: TaskMetadata) -> int | None:
    """Validate the optional integer priority hint field."""
    priority_hint = metadata.get("priority_hint")
    if priority_hint is None:
        return None
    if isinstance(priority_hint, bool) or not isinstance(priority_hint, int):
        msg = "Task metadata 'priority_hint' must be an integer."
        raise TypeError(msg)
    return priority_hint


def _validate_task_metadata(
    metadata: TaskMetadata,
) -> TaskMetadata | None:
    """Validate metadata shape and return a narrowed typed payload."""
    unsupported_keys = set(metadata) - _TASK_METADATA_KEYS
    if unsupported_keys:
        keys = ", ".join(repr(key) for key in sorted(unsupported_keys, key=repr))
        msg = f"Unsupported task metadata keys: {keys}"
        raise ValueError(msg)

    validated: TaskMetadata = {}
    operation_name = _validate_string_metadata_field(metadata, "operation_name")
    if operation_name is not None:
        validated["operation_name"] = operation_name

    correlation_id = _validate_string_metadata_field(metadata, "correlation_id")
    if correlation_id is not None:
        validated["correlation_id"] = correlation_id

    priority_hint = _validate_priority_hint_field(metadata)
    if priority_hint is not None:
        validated["priority_hint"] = priority_hint

    return validated or None


def _validate_task_create_kwargs(kwargs: dict[str, object]) -> TaskCreateKwargs:
    """Validate accepted task-creation kwargs and return a typed payload."""
    unexpected_keys = set(kwargs) - _TASK_CREATE_KWARGS_KEYS
    if unexpected_keys:
        keys = ", ".join(sorted(unexpected_keys, key=repr))
        msg = f"Unsupported task creation kwargs: {keys}"
        raise TypeError(msg)
    return typ.cast("TaskCreateKwargs", kwargs)


def _create_with_optional_metadata[T](
    *,
    loop: asyncio.AbstractEventLoop,
    task_creator: typ.Callable[..., asyncio.Task[T]],
    coro: cabc.Coroutine[object, object, T],
    task_kwargs: TaskCreateKwargs,
) -> asyncio.Task[T]:
    """Create a task and forward metadata only when a task factory is present."""
    name = task_kwargs.get("name")
    context = task_kwargs.get("context")
    eager_start = task_kwargs.get("eager_start")
    validated_metadata = task_kwargs.get("metadata")

    if validated_metadata is None or loop.get_task_factory() is None:
        return task_creator(
            coro,
            name=name,
            context=context,
            eager_start=eager_start,
        )

    return task_creator(
        coro,
        name=name,
        context=context,
        eager_start=eager_start,
        **{TASK_METADATA_KWARG: validated_metadata},
    )


def create_task[T](
    coro: cabc.Coroutine[object, object, T],
    /,
    **kwargs: typ.Unpack[TaskCreateKwargs],
) -> asyncio.Task[T]:
    """Create an asyncio task with optional task-factory metadata."""
    task_kwargs = _validate_task_create_kwargs(kwargs)
    metadata = task_kwargs.get("metadata")
    if metadata is not None:
        task_kwargs["metadata"] = _validate_task_metadata(metadata)
    loop = asyncio.get_running_loop()
    loop_task_creator = typ.cast(
        "typ.Callable[..., asyncio.Task[T]]",
        loop.create_task,
    )
    return _create_with_optional_metadata(
        loop=loop,
        task_creator=loop_task_creator,
        coro=coro,
        task_kwargs=task_kwargs,
    )


def create_task_in_group[T](
    task_group: asyncio.TaskGroup,
    coro: cabc.Coroutine[object, object, T],
    /,
    **kwargs: typ.Unpack[TaskCreateKwargs],
) -> asyncio.Task[T]:
    """Create a task in `task_group` with optional task-factory metadata."""
    task_kwargs = _validate_task_create_kwargs(kwargs)
    metadata = task_kwargs.get("metadata")
    if metadata is not None:
        task_kwargs["metadata"] = _validate_task_metadata(metadata)
    loop = asyncio.get_running_loop()
    group_task_creator = typ.cast(
        "typ.Callable[..., asyncio.Task[T]]",
        task_group.create_task,
    )
    return _create_with_optional_metadata(
        loop=loop,
        task_creator=group_task_creator,
        coro=coro,
        task_kwargs=task_kwargs,
    )
