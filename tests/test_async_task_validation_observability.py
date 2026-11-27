"""Tests for task-validation logging and metrics instrumentation."""

import asyncio
import json
import typing as typ

import pytest

from episodic import asyncio_tasks
from episodic.asyncio_tasks import (
    configure_task_validation_metrics,
    create_task,
    create_task_in_group,
)
from episodic.logging import LoggerHandle, LogLevel
from tests.fixtures.async_task_factory_observability import (
    METRIC_NAME,
    TASK_NAME,
    UNSUPPORTED_KWARGS_CASE,
    UNSUPPORTED_TASK_KWARGS,
    VALIDATION_CASES,
    FailingTaskValidationMetrics,
    FakeTaskValidationMetrics,
    SpyLogger,
    ValidationCase,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc


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


def _trigger(case: ValidationCase, *, task_name: str = TASK_NAME) -> None:
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


@pytest.mark.parametrize("case", VALIDATION_CASES)
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
    assert payload["task_name"] == TASK_NAME, (
        f"expected task_name {TASK_NAME!r}, got {payload['task_name']!r}"
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


@pytest.mark.parametrize("case", VALIDATION_CASES)
def test_validation_failure_increments_categorised_counter(
    case: ValidationCase,
    validation_metrics: FakeTaskValidationMetrics,
) -> None:
    """Each validation failure increments the counter with its category."""
    _trigger(case)

    assert validation_metrics.counters == [(METRIC_NAME, case.metric_labels)], (
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
            create_task(coro, **UNSUPPORTED_TASK_KWARGS)
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
                name=TASK_NAME,
                **UNSUPPORTED_TASK_KWARGS,
            )
    finally:
        coro.close()

    payload = _single_log_payload(spy_logger)
    assert payload["task_name"] == TASK_NAME, (
        f"expected task_name {TASK_NAME!r}, got {payload['task_name']!r}"
    )
    assert validation_metrics.counters == [
        (
            METRIC_NAME,
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
        _trigger(UNSUPPORTED_KWARGS_CASE)
        assert metrics.counters == [
            (
                METRIC_NAME,
                {
                    "error_type": "TypeError",
                    "validation_kind": "unsupported_task_kwargs",
                },
            )
        ], f"expected one counter increment, got {metrics.counters!r}"

        configure_task_validation_metrics(None)
        _trigger(UNSUPPORTED_KWARGS_CASE)
    finally:
        configure_task_validation_metrics(None)

    assert len(metrics.counters) == 1, (
        "a cleared metrics sink must not receive further increments"
    )


class _CustomSinkError(Exception):
    """Stand-in for an adapter-specific telemetry failure."""


class _ProcessControlError(BaseException):
    """Stand-in for a process-control exception that must propagate."""


@pytest.mark.parametrize(
    "error_type",
    [OSError, AssertionError, _CustomSinkError],
    ids=["os_error", "assertion_error", "custom_error"],
)
def test_validation_error_survives_logging_sink_failure(
    monkeypatch: pytest.MonkeyPatch,
    validation_metrics: FakeTaskValidationMetrics,
    error_type: type[Exception],
) -> None:
    """A failing log sink must not replace the validation error."""

    def _fail(logger: object, template: str, *args: object) -> None:
        """Raise as a broken logging backend would."""
        del logger, template, args
        msg = "log sink unavailable"
        raise error_type(msg)

    monkeypatch.setattr(asyncio_tasks, "log_error", _fail)

    _trigger(UNSUPPORTED_KWARGS_CASE)

    assert validation_metrics.counters == [
        (
            METRIC_NAME,
            {"error_type": "TypeError", "validation_kind": "unsupported_task_kwargs"},
        )
    ], "a logging failure must not suppress the counter increment"


@pytest.mark.parametrize(
    "error_type",
    [OSError, AssertionError, _CustomSinkError],
    ids=["os_error", "assertion_error", "custom_error"],
)
def test_validation_error_survives_metrics_sink_failure(
    spy_logger: SpyLogger,
    error_type: type[Exception],
) -> None:
    """A failing metrics sink must not replace the validation error."""
    configure_task_validation_metrics(
        FailingTaskValidationMetrics(error_type=error_type)
    )
    try:
        _trigger(UNSUPPORTED_KWARGS_CASE)
    finally:
        configure_task_validation_metrics(None)

    payload = _single_log_payload(spy_logger)
    assert payload["task_name"] == TASK_NAME, (
        "a metrics failure must not suppress the ERROR log record"
    )


def test_telemetry_sink_process_control_errors_propagate(
    monkeypatch: pytest.MonkeyPatch,
    validation_metrics: FakeTaskValidationMetrics,
) -> None:
    """Process-control failures from a sink are never swallowed."""

    def _interrupt(logger: object, template: str, *args: object) -> None:
        """Raise as an interrupted process would."""
        del logger, template, args
        msg = "interrupted while logging"
        raise _ProcessControlError(msg)

    monkeypatch.setattr(asyncio_tasks, "log_error", _interrupt)

    coro = asyncio.sleep(0)
    try:
        with pytest.raises(_ProcessControlError):
            create_task(coro, name=TASK_NAME, **UNSUPPORTED_TASK_KWARGS)
    finally:
        coro.close()

    assert validation_metrics.counters == [], (
        "a process-control failure must stop the telemetry path"
    )
