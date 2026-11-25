"""Utilities for metadata-aware asyncio task creation.

This module centralizes task creation so asynchronous orchestration can attach
consistent metadata for custom event-loop task factories while preserving safe
behaviour when no factory is installed. Rejected task-creation kwargs and
metadata are reported at ERROR level and counted through an injectable metrics
sink so deployments can track validation failure rates.

A composition root installs the sink it wants failures reported to through
``configure_task_validation_metrics``; the default sink is inert.
"""

import asyncio
import dataclasses as dc
import typing as typ

from episodic.logging import format_log_event, get_logger, log_error
from episodic.observability import MetricsPort, NoopMetrics

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import contextvars as cv

logger = get_logger(__name__)

TASK_METADATA_KWARG = "episodic_task_metadata"
_TASK_METADATA_KEYS = frozenset({"operation_name", "correlation_id", "priority_hint"})
_METRIC_VALIDATION_FAILURES = "episodic.task_validation.failures"
_UNNAMED_TASK = "<unnamed>"


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


class TaskValidationMetricsPort(MetricsPort, typ.Protocol):
    """Bounded-cardinality metrics sink for task-validation failures.

    This protocol narrows :class:`episodic.observability.MetricsPort` to name
    the task-validation metrics boundary; it does not introduce new methods.
    Adapters that satisfy ``MetricsPort`` therefore satisfy this port as well.
    """


@dc.dataclass(frozen=True, slots=True)
class _NoopTaskValidationMetrics(NoopMetrics):
    """Default metrics sink used when no backend is wired."""


_metrics: TaskValidationMetricsPort = _NoopTaskValidationMetrics()


def configure_task_validation_metrics(
    metrics: TaskValidationMetricsPort | None,
) -> None:
    """Install the metrics sink that counts task-validation failures.

    Parameters
    ----------
    metrics : TaskValidationMetricsPort | None
        Sink that receives one counter increment per rejected task-creation
        request. ``None`` restores the module's no-op sink.

    Examples
    --------
    Reset the module to its inert default sink:

    >>> configure_task_validation_metrics(None)
    """
    global _metrics
    _metrics = _NoopTaskValidationMetrics() if metrics is None else metrics


def _display_task_name(task_name: str | None) -> str:
    """Return the task name to report in log records."""
    return _UNNAMED_TASK if task_name is None else task_name


def _abort_validation(
    exception: TypeError | ValueError,
    *,
    task_name: str | None,
    fields: cabc.Mapping[str, object],
    labels: cabc.Mapping[str, str],
) -> typ.NoReturn:
    """Record one task-validation failure, then raise its exception."""
    error_type = type(exception).__name__
    log_error(
        logger,
        "%s",
        format_log_event(
            "task_validation_failed",
            task_name=_display_task_name(task_name),
            error_type=error_type,
            **fields,
        ),
    )
    _metrics.increment_counter(
        _METRIC_VALIDATION_FAILURES,
        labels={"error_type": error_type, **labels},
    )
    raise exception


def _validate_string_metadata_field(
    metadata: TaskMetadata,
    field_name: str,
    *,
    task_name: str | None = None,
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
        _abort_validation(
            TypeError(msg),
            task_name=task_name,
            fields={
                "validation_kind": "metadata_field_type",
                "field_name": field_name,
                "expected_type": "str",
                "actual_type": type(value).__name__,
            },
            labels={"field_name": field_name},
        )
    if not value:
        msg = f"Task metadata {field_name!r} must be a non-empty string."
        _abort_validation(
            ValueError(msg),
            task_name=task_name,
            fields={
                "validation_kind": "metadata_field_empty",
                "field_name": field_name,
                "expected_type": "non-empty str",
                "actual_type": "empty str",
            },
            labels={"field_name": field_name},
        )
    return value


def _validate_priority_hint_field(
    metadata: TaskMetadata,
    *,
    task_name: str | None = None,
) -> int | None:
    """Validate the optional integer priority hint field."""
    priority_hint = metadata.get("priority_hint")
    if priority_hint is None:
        return None
    if isinstance(priority_hint, bool) or not isinstance(priority_hint, int):
        msg = "Task metadata 'priority_hint' must be an integer."
        _abort_validation(
            TypeError(msg),
            task_name=task_name,
            fields={
                "validation_kind": "metadata_field_type",
                "field_name": "priority_hint",
                "expected_type": "int",
                "actual_type": type(priority_hint).__name__,
            },
            labels={"field_name": "priority_hint"},
        )
    return priority_hint


def _validate_task_metadata(
    metadata: TaskMetadata,
    *,
    task_name: str | None = None,
) -> TaskMetadata | None:
    """Validate metadata shape and return a narrowed typed payload."""
    unsupported_keys = set(metadata) - _TASK_METADATA_KEYS
    if unsupported_keys:
        keys = ", ".join(repr(key) for key in sorted(unsupported_keys, key=repr))
        msg = f"Unsupported task metadata keys: {keys}"
        _abort_validation(
            ValueError(msg),
            task_name=task_name,
            fields={
                "validation_kind": "unsupported_metadata_keys",
                "unexpected_keys": keys,
                "expected_keys": ", ".join(sorted(_TASK_METADATA_KEYS)),
            },
            labels={"validation_kind": "unsupported_metadata_keys"},
        )

    validated: TaskMetadata = {}
    operation_name = _validate_string_metadata_field(
        metadata,
        "operation_name",
        task_name=task_name,
    )
    if operation_name is not None:
        validated["operation_name"] = operation_name

    correlation_id = _validate_string_metadata_field(
        metadata,
        "correlation_id",
        task_name=task_name,
    )
    if correlation_id is not None:
        validated["correlation_id"] = correlation_id

    priority_hint = _validate_priority_hint_field(metadata, task_name=task_name)
    if priority_hint is not None:
        validated["priority_hint"] = priority_hint

    return validated or None


def _validate_task_create_kwargs(
    kwargs: cabc.Mapping[str, object],
    *,
    task_name: str | None = None,
) -> TaskCreateKwargs:
    """Validate accepted task-creation kwargs and return a typed payload."""
    unexpected_keys = set(kwargs) - _TASK_CREATE_KWARGS_KEYS
    if unexpected_keys:
        keys = ", ".join(sorted(unexpected_keys, key=repr))
        msg = f"Unsupported task creation kwargs: {keys}"
        _abort_validation(
            TypeError(msg),
            task_name=task_name,
            fields={
                "validation_kind": "unsupported_task_kwargs",
                "unexpected_keys": keys,
                "expected_keys": ", ".join(sorted(_TASK_CREATE_KWARGS_KEYS)),
            },
            labels={"validation_kind": "unsupported_task_kwargs"},
        )
    return typ.cast("TaskCreateKwargs", dict(kwargs))


def _validated_task_kwargs(
    kwargs: cabc.Mapping[str, object],
    *,
    task_name: str | None,
) -> TaskCreateKwargs:
    """Validate task-creation kwargs and their nested metadata."""
    task_kwargs = _validate_task_create_kwargs(kwargs, task_name=task_name)
    metadata = task_kwargs.get("metadata")
    if metadata is not None:
        task_kwargs["metadata"] = _validate_task_metadata(
            metadata,
            task_name=task_name,
        )
    return task_kwargs


def _create_with_optional_metadata[T](
    *,
    loop: asyncio.AbstractEventLoop,
    task_creator: cabc.Callable[..., asyncio.Task[T]],
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
    task_name = kwargs.get("name")
    task_kwargs = _validated_task_kwargs(kwargs, task_name=task_name)
    loop = asyncio.get_running_loop()
    loop_task_creator = typ.cast(
        "cabc.Callable[..., asyncio.Task[T]]",
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
    task_name = kwargs.get("name")
    task_kwargs = _validated_task_kwargs(kwargs, task_name=task_name)
    loop = asyncio.get_running_loop()
    group_task_creator = typ.cast(
        "cabc.Callable[..., asyncio.Task[T]]",
        task_group.create_task,
    )
    return _create_with_optional_metadata(
        loop=loop,
        task_creator=group_task_creator,
        coro=coro,
        task_kwargs=task_kwargs,
    )
