"""Tests for task-validation logging and metrics instrumentation."""

import asyncio
import json
import typing as typ

import pytest

from episodic import asyncio_tasks
from episodic.asyncio_tasks import (
    TaskCreateKwargs,
    TaskMetadata,
    configure_task_validation_metrics,
    create_task,
    create_task_in_group,
)
from episodic.logging import LoggerHandle, LogLevel
from tests.fixtures.async_task_factory_observability import (
    FakeTaskValidationMetrics,
    SpyLogger,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_METRIC_NAME = "episodic.task_validation.failures"
_TASK_NAME = "observability-task"
_UNSUPPORTED_KWARGS: typ.Final = typ.cast(
    "TaskCreateKwargs",
    {"unsupported_kwarg": "value"},
)


def _with_unsupported_kwargs(
    coro: cabc.Coroutine[object, object, object],
    task_name: str,
) -> object:
    """Create a task with an unsupported keyword argument."""
    return create_task(coro, name=task_name, **_UNSUPPORTED_KWARGS)


def _with_unsupported_metadata_key(
    coro: cabc.Coroutine[object, object, object],
    task_name: str,
) -> object:
    """Create a task with an unsupported metadata key."""
    metadata = typ.cast("TaskMetadata", {"unsupported_key": "nope"})
    return create_task(coro, name=task_name, metadata=metadata)


def _with_non_string_operation_name(
    coro: cabc.Coroutine[object, object, object],
    task_name: str,
) -> object:
    """Create a task whose operation name has the wrong type."""
    metadata = typ.cast("TaskMetadata", {"operation_name": 123})
    return create_task(coro, name=task_name, metadata=metadata)


def _with_empty_operation_name(
    coro: cabc.Coroutine[object, object, object],
    task_name: str,
) -> object:
    """Create a task whose operation name is empty."""
    return create_task(coro, name=task_name, metadata={"operation_name": ""})


def _with_non_integer_priority_hint(
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


_UNSUPPORTED_KWARGS_CASE = ValidationCase(
    make_call=_with_unsupported_kwargs,
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
_UNSUPPORTED_METADATA_CASE = ValidationCase(
    make_call=_with_unsupported_metadata_key,
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
_NON_STRING_FIELD_CASE = ValidationCase(
    make_call=_with_non_string_operation_name,
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
_EMPTY_FIELD_CASE = ValidationCase(
    make_call=_with_empty_operation_name,
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
_NON_INTEGER_PRIORITY_CASE = ValidationCase(
    make_call=_with_non_integer_priority_hint,
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
_VALIDATION_CASES = [
    pytest.param(_UNSUPPORTED_KWARGS_CASE, id="unsupported_task_kwargs"),
    pytest.param(_UNSUPPORTED_METADATA_CASE, id="unsupported_metadata_keys"),
    pytest.param(_NON_STRING_FIELD_CASE, id="non_string_metadata_field"),
    pytest.param(_EMPTY_FIELD_CASE, id="empty_metadata_field"),
    pytest.param(_NON_INTEGER_PRIORITY_CASE, id="non_integer_priority_hint"),
]


@pytest.fixture
def spy_logger(monkeypatch: pytest.MonkeyPatch) -> SpyLogger:
    """Install a recording backend behind the module logger handle."""
    spy = SpyLogger()
    monkeypatch.setattr(asyncio_tasks, "logger", LoggerHandle(spy))
    return spy


@pytest.fixture
def validation_metrics() -> cabc.Iterator[FakeTaskValidationMetrics]:
    """Install a recording metrics sink and restore the no-op afterwards."""
    metrics = FakeTaskValidationMetrics()
    configure_task_validation_metrics(metrics)
    yield metrics
    configure_task_validation_metrics(None)


def _trigger(case: ValidationCase, *, task_name: str = _TASK_NAME) -> None:
    """Invoke one validation failure and close the unstarted coroutine."""
    coro = asyncio.sleep(0)
    try:
        with pytest.raises(case.expected_error, match=case.exception_pattern):
            case.make_call(coro, task_name)
    finally:
        coro.close()


def _single_log_payload(spy: SpyLogger) -> dict[str, object]:
    """Return the parsed payload of the single expected log record."""
    assert len(spy.calls) == 1, f"expected one log call, got {spy.calls!r}"
    return typ.cast("dict[str, object]", json.loads(spy.calls[0][1]))


@pytest.mark.parametrize("case", _VALIDATION_CASES)
def test_validation_failure_emits_one_error_record(
    case: ValidationCase,
    spy_logger: SpyLogger,
    validation_metrics: FakeTaskValidationMetrics,
) -> None:
    """Each validation failure emits one structured ERROR record."""
    _trigger(case)

    assert len(spy_logger.calls) == 1, (
        f"expected one log call, got {spy_logger.calls!r}"
    )
    level, message, exc_info, stack_info = spy_logger.calls[0]
    assert level is LogLevel.ERROR, f"expected ERROR level, got {level!r}"
    assert exc_info is None, "validation logging must not attach exception info"
    assert stack_info is False, "validation logging must not attach stack info"
    payload = typ.cast("dict[str, object]", json.loads(message))
    assert payload["event"] == "task_validation_failed", (
        f"expected the task_validation_failed event, got {payload!r}"
    )
    assert payload["task_name"] == _TASK_NAME, (
        f"expected task_name {_TASK_NAME!r}, got {payload['task_name']!r}"
    )
    assert payload["error_type"] == case.expected_error.__name__, (
        f"expected error_type {case.expected_error.__name__!r}, "
        f"got {payload['error_type']!r}"
    )
    for field_name, expected in case.log_fields.items():
        assert payload[field_name] == expected, (
            f"expected log field {field_name!r} == {expected!r}, "
            f"got {payload.get(field_name)!r}"
        )


@pytest.mark.parametrize("case", _VALIDATION_CASES)
def test_validation_failure_increments_categorised_counter(
    case: ValidationCase,
    validation_metrics: FakeTaskValidationMetrics,
) -> None:
    """Each validation failure increments the counter with its category."""
    _trigger(case)

    assert validation_metrics.counters == [(_METRIC_NAME, case.metric_labels)], (
        f"expected one counter increment for {case.metric_labels!r}, "
        f"got {validation_metrics.counters!r}"
    )


def test_validation_record_names_unnamed_tasks(
    spy_logger: SpyLogger,
    validation_metrics: FakeTaskValidationMetrics,
) -> None:
    """A caller that omits the task name is reported as `<unnamed>`."""
    coro = asyncio.sleep(0)
    try:
        with pytest.raises(TypeError, match="unsupported_kwarg"):
            create_task(coro, **_UNSUPPORTED_KWARGS)
    finally:
        coro.close()

    payload = _single_log_payload(spy_logger)
    assert payload["task_name"] == "<unnamed>", (
        f"expected task_name '<unnamed>', got {payload['task_name']!r}"
    )


def test_task_group_creation_records_validation_failure(
    spy_logger: SpyLogger,
    validation_metrics: FakeTaskValidationMetrics,
) -> None:
    """`create_task_in_group` reports failures through the same path."""
    coro = asyncio.sleep(0)
    try:
        with pytest.raises(TypeError, match="unsupported_kwarg"):
            create_task_in_group(
                asyncio.TaskGroup(),
                coro,
                name=_TASK_NAME,
                **_UNSUPPORTED_KWARGS,
            )
    finally:
        coro.close()

    payload = _single_log_payload(spy_logger)
    assert payload["task_name"] == _TASK_NAME, (
        f"expected task_name {_TASK_NAME!r}, got {payload['task_name']!r}"
    )
    assert validation_metrics.counters == [
        (
            _METRIC_NAME,
            {"error_type": "TypeError", "validation_kind": "unsupported_task_kwargs"},
        )
    ], f"expected one counter increment, got {validation_metrics.counters!r}"


@pytest.mark.asyncio
async def test_successful_task_creation_is_not_reported(
    spy_logger: SpyLogger,
    validation_metrics: FakeTaskValidationMetrics,
) -> None:
    """A valid task-creation request logs nothing and counts nothing."""

    async def _job() -> str:
        """Yield once to the event loop and return ``"ok"``."""
        await asyncio.sleep(0)
        return "ok"

    task = create_task(
        _job(),
        name="observability-ok",
        metadata={"operation_name": "tests.observability.ok"},
    )

    assert await task == "ok", "expected the created task to complete normally"
    assert spy_logger.calls == [], "valid task creation must not log"
    assert validation_metrics.counters == [], "valid task creation must not count"


def test_configure_task_validation_metrics_installs_and_clears_sink(
    spy_logger: SpyLogger,
) -> None:
    """The public configure function installs a sink and None restores no-op."""
    metrics = FakeTaskValidationMetrics()
    configure_task_validation_metrics(metrics)
    try:
        _trigger(_UNSUPPORTED_KWARGS_CASE)
        assert metrics.counters == [
            (
                _METRIC_NAME,
                {
                    "error_type": "TypeError",
                    "validation_kind": "unsupported_task_kwargs",
                },
            )
        ], f"expected one counter increment, got {metrics.counters!r}"

        configure_task_validation_metrics(None)
        _trigger(_UNSUPPORTED_KWARGS_CASE)
    finally:
        configure_task_validation_metrics(None)

    assert len(metrics.counters) == 1, (
        "a cleared metrics sink must not receive further increments"
    )
