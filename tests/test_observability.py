"""Focused tests for synchronous tracing adapters."""

import dataclasses as dc
import typing as typ

from episodic.observability import (
    NoopTracer,
    RecordingTracer,
    StructuredLogMetrics,
    StructuredLogTracer,
)

if typ.TYPE_CHECKING:
    from collections import abc as cabc


@dc.dataclass(slots=True)
class _RecordingLogger:
    """Capture structured logger events without process-wide configuration."""

    events: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)

    def info(self, message: str, /, *, extra: cabc.Mapping[str, str]) -> None:
        """Record a structured INFO event."""
        self.events.append((message, dict(extra)))


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


def test_structured_log_tracer_allows_bounded_operation_attributes() -> None:
    """Structured spans retain only allow-listed bounded operation attributes."""
    logger = _RecordingLogger()
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
    assert logger.events == expected_events, logger.events


def test_structured_log_metrics_emits_latency_and_value_events() -> None:
    """Structured metrics retain their event names and payload fields."""
    logger = _RecordingLogger()
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
            "operation": "generation_run.execute",
        },
    )
    expected_value_event = (
        "metric_value",
        {
            "metric_name": "generation_run.queue_depth",
            "value": "2.0",
            "operation": "generation_run.execute",
        },
    )

    assert logger.events == [expected_latency_event, expected_value_event], (
        logger.events
    )


def test_noop_tracer_supports_synchronous_span_contexts() -> None:
    """No-op tracing leaves synchronous operation control flow unchanged."""
    with NoopTracer().start_span("generation_run.admission", attributes={}):
        pass
