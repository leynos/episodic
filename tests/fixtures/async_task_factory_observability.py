"""Test doubles and scenario data for task-validation observability tests."""

import dataclasses as dc
import typing as typ

import pytest

from episodic import logging as episodic_logging
from episodic.asyncio_tasks import TaskCreateKwargs, TaskMetadata, create_task
from episodic.observability import NoopMetrics

if typ.TYPE_CHECKING:
    import collections.abc as cabc

TASK_NAME = "observability-task"
METRIC_NAME = "episodic.task_validation.failures"
UNSUPPORTED_TASK_KWARGS: typ.Final = typ.cast(
    "TaskCreateKwargs",
    {"unsupported_kwarg": "value"},
)


class SpyLogger:
    """Record log calls dispatched through the Episodic logging port."""

    def __init__(self) -> None:
        """Initialise an empty call record."""
        self.calls: list[
            tuple[int | episodic_logging.LogLevel, str, object | None, bool]
        ] = []

    def error(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record an ERROR-level call through the convenience method."""
        self.calls.append((
            episodic_logging.LogLevel.ERROR,
            message,
            exc_info,
            stack_info,
        ))

    def log(
        self,
        level: int | episodic_logging.LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record a fallback call; the logging port prefers `error` instead."""
        self.calls.append((level, message, exc_info, stack_info))


@dc.dataclass(frozen=True, slots=True)
class FakeTaskValidationMetrics(NoopMetrics):
    """Record counter increments for task-validation assertions."""

    counters: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture one counter increment."""
        self.counters.append((name, dict(labels)))


@dc.dataclass(frozen=True, slots=True)
class FailingTaskValidationMetrics(NoopMetrics):
    """Metrics sink that fails every counter increment."""

    error_type: type[Exception] = OSError

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Raise the configured sink failure."""
        msg = f"metrics sink unavailable for {name} ({dict(labels)!r})"
        raise self.error_type(msg)


def create_with_unsupported_kwargs(
    coro: cabc.Coroutine[object, object, object],
    task_name: str,
) -> object:
    """Create a task with an unsupported keyword argument."""
    return create_task(coro, name=task_name, **UNSUPPORTED_TASK_KWARGS)


def create_with_unsupported_metadata_key(
    coro: cabc.Coroutine[object, object, object],
    task_name: str,
) -> object:
    """Create a task with an unsupported metadata key."""
    metadata = typ.cast("TaskMetadata", {"unsupported_key": "nope"})
    return create_task(coro, name=task_name, metadata=metadata)


def create_with_non_string_operation_name(
    coro: cabc.Coroutine[object, object, object],
    task_name: str,
) -> object:
    """Create a task whose operation name has the wrong type."""
    metadata = typ.cast("TaskMetadata", {"operation_name": 123})
    return create_task(coro, name=task_name, metadata=metadata)


def create_with_empty_operation_name(
    coro: cabc.Coroutine[object, object, object],
    task_name: str,
) -> object:
    """Create a task whose operation name is empty."""
    return create_task(coro, name=task_name, metadata={"operation_name": ""})


def create_with_non_integer_priority_hint(
    coro: cabc.Coroutine[object, object, object],
    task_name: str,
) -> object:
    """Create a task whose priority hint has the wrong type."""
    metadata = typ.cast("TaskMetadata", {"priority_hint": "high"})
    return create_task(coro, name=task_name, metadata=metadata)


class ValidationCase(typ.NamedTuple):
    """Describe one validation failure and its expected diagnostics."""

    make_call: cabc.Callable[[cabc.Coroutine[object, object, object], str], object]
    expected_error: type[Exception]
    exception_pattern: str
    log_fields: dict[str, object]
    metric_labels: dict[str, str]


UNSUPPORTED_KWARGS_CASE = ValidationCase(
    make_call=create_with_unsupported_kwargs,
    expected_error=TypeError,
    exception_pattern="unsupported_kwarg",
    log_fields={
        "validation_kind": "unsupported_task_kwargs",
        "unexpected_keys": "unsupported_kwarg",
    },
    metric_labels={
        "error_type": "TypeError",
        "validation_kind": "unsupported_task_kwargs",
    },
)
UNSUPPORTED_METADATA_CASE = ValidationCase(
    make_call=create_with_unsupported_metadata_key,
    expected_error=ValueError,
    exception_pattern="unsupported_key",
    log_fields={
        "validation_kind": "unsupported_metadata_keys",
        "unexpected_keys": "'unsupported_key'",
    },
    metric_labels={
        "error_type": "ValueError",
        "validation_kind": "unsupported_metadata_keys",
    },
)
NON_STRING_FIELD_CASE = ValidationCase(
    make_call=create_with_non_string_operation_name,
    expected_error=TypeError,
    exception_pattern="operation_name",
    log_fields={
        "validation_kind": "metadata_field_type",
        "field_name": "operation_name",
        "expected_type": "str",
        "actual_type": "int",
    },
    metric_labels={"error_type": "TypeError", "field_name": "operation_name"},
)
EMPTY_FIELD_CASE = ValidationCase(
    make_call=create_with_empty_operation_name,
    expected_error=ValueError,
    exception_pattern="non-empty string",
    log_fields={
        "validation_kind": "metadata_field_empty",
        "field_name": "operation_name",
        "expected_type": "non-empty str",
        "actual_type": "empty str",
    },
    metric_labels={"error_type": "ValueError", "field_name": "operation_name"},
)
NON_INTEGER_PRIORITY_CASE = ValidationCase(
    make_call=create_with_non_integer_priority_hint,
    expected_error=TypeError,
    exception_pattern="priority_hint",
    log_fields={
        "validation_kind": "metadata_field_type",
        "field_name": "priority_hint",
        "expected_type": "int",
        "actual_type": "str",
    },
    metric_labels={"error_type": "TypeError", "field_name": "priority_hint"},
)
VALIDATION_CASES = [
    pytest.param(UNSUPPORTED_KWARGS_CASE, id="unsupported_task_kwargs"),
    pytest.param(UNSUPPORTED_METADATA_CASE, id="unsupported_metadata_keys"),
    pytest.param(NON_STRING_FIELD_CASE, id="non_string_metadata_field"),
    pytest.param(EMPTY_FIELD_CASE, id="empty_metadata_field"),
    pytest.param(NON_INTEGER_PRIORITY_CASE, id="non_integer_priority_hint"),
]
