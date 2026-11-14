"""Focused tests for synchronous tracing adapters."""

import dataclasses as dc
import json
import typing as typ
from unittest import mock

from episodic.logging import LoggerHandle, LogLevel
from episodic.observability import (
    NoopMetrics,
    NoopTracer,
    RecordingTracer,
    StructuredLogMetrics,
    StructuredLogTracer,
    _structured,
    configure_structured_observability,
)


@dc.dataclass(slots=True)
class _RecordingLogger:
    """Capture structured logger events without process-wide configuration."""

    events: list[tuple[str, dict[str, object]]] = dc.field(default_factory=list)

    def log(
        self,
        level: int | LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record a structured INFO event."""
        del exc_info, stack_info
        assert level == 20, "structured observability events must be INFO logs"
        payload = json.loads(message)
        event = typ.cast("str", payload.pop("event"))
        self.events.append((event, typ.cast("dict[str, object]", payload)))


def test_recording_tracer_preserves_span_details_and_completion() -> None:
    """Recording spans keep copied attributes and complete after context exit."""
    tracer = RecordingTracer()
    attributes = {"run_id": "run-42", "operation": "admit"}

    with tracer.start_span("generation_run.admission", attributes=attributes):
        attributes["run_id"] = "mutated-after-start"

    assert tracer.spans[0].name == "generation_run.admission", tracer.spans
    assert tracer.spans[0].attributes == {
        "run_id": "run-42",
        "operation": "admit",
    }, tracer.spans
    assert tracer.spans[0].is_completed, tracer.spans


def test_configure_structured_observability_selects_sinks_by_level() -> None:
    """Composition roots share one level-aware structured-sink selector."""
    with mock.patch.object(
        _structured,
        "configure_structured_logging",
        side_effect=(LogLevel.INFO, LogLevel.WARNING),
    ) as configure_logging:
        info_metrics, info_tracer = configure_structured_observability("INFO")
        warning_metrics, warning_tracer = configure_structured_observability("WARNING")

    configure_logging.assert_has_calls([mock.call("INFO"), mock.call("WARNING")])
    assert isinstance(info_metrics, StructuredLogMetrics), (
        "INFO selects the structured metrics adapter"
    )
    assert isinstance(info_tracer, StructuredLogTracer), (
        "INFO selects the structured tracing adapter"
    )
    assert isinstance(warning_metrics, NoopMetrics), (
        "levels above INFO select a no-op metrics adapter"
    )
    assert isinstance(warning_tracer, NoopTracer), (
        "levels above INFO select a no-op tracing adapter"
    )


def test_structured_log_tracer_allows_bounded_operation_attributes() -> None:
    """Structured spans retain only allow-listed bounded operation attributes."""
    recorder = _RecordingLogger()
    logger = LoggerHandle(recorder)
    tracer = StructuredLogTracer(logger=logger)

    with tracer.start_span(
        "generation_run.admission",
        attributes={
            "operation": "generation_run.admission",
            "run_id": "run-42",
            "access_token": "secret-value",
        },
    ) as span:
        span.set_attribute("outcome", "rejected")
        span.set_attribute("failure_category", "launcher.overloaded")

    expected_events = [
        (
            "trace_span_started",
            {
                "span_name": "generation_run.admission",
                "operation": "generation_run.admission",
            },
        ),
        (
            "trace_span_completed",
            {
                "span_name": "generation_run.admission",
                "operation": "generation_run.admission",
                "outcome": "rejected",
                "failure_category": "launcher.overloaded",
            },
        ),
    ]
    assert recorder.events == expected_events, recorder.events


def test_structured_log_metrics_emits_latency_and_value_events() -> None:
    """Structured metrics retain their event names and payload fields."""
    recorder = _RecordingLogger()
    logger = LoggerHandle(recorder)
    metrics = StructuredLogMetrics(logger=logger)
    labels = {"operation": "generation_run.execute"}

    metrics.observe_latency_ms(
        "generation_run.duration_ms",
        123.45,
        labels=labels,
    )
    metrics.observe_value(
        "generation_run.queue_depth",
        2.0,
        labels=labels,
    )

    expected_latency_event = (
        "metric_latency",
        {
            "metric_name": "generation_run.duration_ms",
            "value": "123.45",
            "labels": {"operation": "generation_run.execute"},
        },
    )
    expected_value_event = (
        "metric_value",
        {
            "metric_name": "generation_run.queue_depth",
            "value": "2.0",
            "labels": {"operation": "generation_run.execute"},
        },
    )

    assert recorder.events == [expected_latency_event, expected_value_event], (
        recorder.events
    )


def test_structured_log_metrics_preserves_reserved_parameter_labels() -> None:
    """Labels stay namespaced so reserved event fields cannot replace them."""
    recorder = _RecordingLogger()
    metrics = StructuredLogMetrics(logger=LoggerHandle(recorder))
    labels = {
        "event": "label-event",
        "logger": "label-logger",
        "metric_name": "label-metric",
        "value": "label-value",
    }

    metrics.increment_counter(
        "requests",
        labels=labels,
    )
    metrics.observe_value("queue_depth", 2.0, labels=labels)

    expected_events = [
        (
            "metric_counter",
            {"metric_name": "requests", "labels": labels},
        ),
        (
            "metric_value",
            {"metric_name": "queue_depth", "value": "2.0", "labels": labels},
        ),
    ]
    assert recorder.events == expected_events, (
        "reserved event fields must remain distinct from metric labels"
    )


def test_noop_tracer_supports_synchronous_span_contexts() -> None:
    """No-op tracing leaves synchronous operation control flow unchanged."""
    with NoopTracer().start_span("generation_run.admission", attributes={}):
        pass
