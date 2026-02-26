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
    metadata: typ.Mapping[str, object] | None


def _validate_optional_text_field(
    metadata: typ.Mapping[str, object],
    *,
    key: str,
) -> str | None:
    """Validate an optional non-empty string metadata field."""
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        msg = f"Task metadata {key!r} must be a non-empty string."
        raise TypeError(msg)
    return value


def _validate_priority_hint(metadata: typ.Mapping[str, object]) -> int | None:
    """Validate an optional integer priority hint."""
    priority_hint = metadata.get("priority_hint")
    if priority_hint is None:
        return None
    if isinstance(priority_hint, bool) or not isinstance(priority_hint, int):
        msg = "Task metadata 'priority_hint' must be an integer."
        raise TypeError(msg)
    return priority_hint


def _validate_task_metadata(
    metadata: typ.Mapping[str, object] | None,
) -> TaskMetadata | None:
    """Validate metadata shape and return a narrowed typed payload."""
    if metadata is None:
        return None

    unsupported_keys = set(metadata) - _TASK_METADATA_KEYS
    if unsupported_keys:
        keys = ", ".join(sorted(unsupported_keys))
        msg = f"Unsupported task metadata keys: {keys}"
        raise ValueError(msg)

    validated: TaskMetadata = {}

    operation_name = _validate_optional_text_field(
        metadata,
        key="operation_name",
    )
    if operation_name is not None:
        validated["operation_name"] = operation_name

    correlation_id = _validate_optional_text_field(
        metadata,
        key="correlation_id",
    )
    if correlation_id is not None:
        validated["correlation_id"] = correlation_id

    priority_hint = _validate_priority_hint(metadata)
    if priority_hint is not None:
        validated["priority_hint"] = priority_hint

    return validated or None


def _resolve_task_kwargs(
    kwargs: typ.Mapping[str, object],
) -> tuple[str | None, cv.Context | None, bool | None, TaskMetadata | None]:
    """Extract typed task kwargs and validated optional metadata."""
    metadata = typ.cast("typ.Mapping[str, object] | None", kwargs.get("metadata"))
    return (
        typ.cast("str | None", kwargs.get("name")),
        typ.cast("cv.Context | None", kwargs.get("context")),
        typ.cast("bool | None", kwargs.get("eager_start")),
        _validate_task_metadata(metadata),
    )


def create_task[T](
    coro: cabc.Coroutine[object, object, T],
    /,
    **kwargs: typ.Unpack[TaskCreateKwargs],
) -> asyncio.Task[T]:
    """Create an asyncio task with optional task-factory metadata."""
    name, context, eager_start, metadata = _resolve_task_kwargs(kwargs)
    if metadata is None or asyncio.get_running_loop().get_task_factory() is None:
        return asyncio.create_task(
            coro,
            name=name,
            context=context,
            eager_start=eager_start,
        )

    create_task_with_factory_kwargs = typ.cast(
        "typ.Callable[..., asyncio.Task[T]]",
        asyncio.create_task,
    )
    return create_task_with_factory_kwargs(
        coro,
        name=name,
        context=context,
        eager_start=eager_start,
        **{TASK_METADATA_KWARG: metadata},
    )


def create_task_in_group[T](
    task_group: asyncio.TaskGroup,
    coro: cabc.Coroutine[object, object, T],
    /,
    **kwargs: typ.Unpack[TaskCreateKwargs],
) -> asyncio.Task[T]:
    """Create a task in `task_group` with optional task-factory metadata."""
    name, context, eager_start, metadata = _resolve_task_kwargs(kwargs)
    if metadata is None or asyncio.get_running_loop().get_task_factory() is None:
        return task_group.create_task(
            coro,
            name=name,
            context=context,
            eager_start=eager_start,
        )

    create_task_with_factory_kwargs = typ.cast(
        "typ.Callable[..., asyncio.Task[T]]",
        task_group.create_task,
    )
    return create_task_with_factory_kwargs(
        coro,
        name=name,
        context=context,
        eager_start=eager_start,
        **{TASK_METADATA_KWARG: metadata},
    )
