"""Outcome classification for one bounded operation observation.

Each case drives the context manager with recording sinks and pins the span
attributes and latency labels it emits, including the case where an exception
escapes after a success outcome was already recorded.
"""

import pytest

from episodic.observability import RecordedSpan, RecordingTracer
from episodic.operation_observation import (
    UNEXPECTED_FAILURE,
    OperationObservation,
)
from tests.canonical_storage._workflow_checkpoint_support import (
    RecordingMetrics,
    StepClock,
)

_SPAN = "qa_artefact.record"


def _observation() -> tuple[OperationObservation, RecordingTracer, RecordingMetrics]:
    """Return an observation and the sinks it reports to."""
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    observation = OperationObservation(
        tracer=tracer,
        metrics=metrics,
        clock=StepClock(),
        span_name=_SPAN,
    )
    return observation, tracer, metrics


def _attributes(outcome: str, *, failure_category: str | None = None) -> dict[str, str]:
    """Return the span attributes an outcome should produce."""
    attributes = {"operation": _SPAN, "outcome": outcome}
    if failure_category is not None:
        attributes["failure_category"] = failure_category
    return attributes


def _labels(outcome: str, *, failure_category: str | None = None) -> dict[str, str]:
    """Return the latency labels an outcome should produce."""
    labels = {"outcome": outcome}
    if failure_category is not None:
        labels["failure_category"] = failure_category
    return labels


def test_success_records_the_outcome_and_one_latency() -> None:
    """A completed operation records its outcome and one latency."""
    observation, tracer, metrics = _observation()

    with observation:
        observation.succeeded("recorded")

    assert tracer.spans == [
        RecordedSpan(
            name=_SPAN,
            attributes=_attributes("recorded"),
            is_completed=True,
        )
    ], "the span should carry the recorded outcome"
    assert metrics.latencies == [(f"{_SPAN}.latency_ms", 1.0, _labels("recorded"))], (
        "the latency should carry the recorded outcome"
    )


def _record_failure_then_raise(observation: OperationObservation) -> None:
    """Record a failure category and then raise, as a caller would."""
    observation.failed("api_error")
    raise RuntimeError("boom")


def _record_success_then_raise(observation: OperationObservation) -> None:
    """Record a success outcome and then raise, as a later read would."""
    observation.succeeded("recorded")
    raise RuntimeError("boom")


def test_failure_category_survives_an_escaping_exception() -> None:
    """A recorded failure category is not overwritten on the way out."""
    observation, tracer, metrics = _observation()

    with pytest.raises(RuntimeError), observation:
        _record_failure_then_raise(observation)

    assert tracer.spans[0].attributes == _attributes(
        "failed", failure_category="api_error"
    ), "the recorded failure category should be preserved"
    assert metrics.latencies[0][2] == _labels("failed", failure_category="api_error"), (
        "the latency should carry the recorded failure category"
    )


def test_exception_after_success_marks_the_operation_failed() -> None:
    """An exception after a success outcome replaces it with a failure."""
    observation, tracer, metrics = _observation()

    with pytest.raises(RuntimeError), observation:
        _record_success_then_raise(observation)

    assert tracer.spans[0].attributes == _attributes(
        "failed", failure_category=UNEXPECTED_FAILURE
    ), "an escaping exception should mark the span failed"
    assert metrics.latencies[0][2] == _labels(
        "failed", failure_category=UNEXPECTED_FAILURE
    ), "the latency should carry the failure"


def test_unclassified_exception_marks_the_operation_failed() -> None:
    """An exception with no recorded outcome is an unexpected failure."""
    observation, tracer, _ = _observation()

    with pytest.raises(RuntimeError), observation:
        raise RuntimeError("boom")

    assert tracer.spans[0].attributes == _attributes(
        "failed", failure_category=UNEXPECTED_FAILURE
    ), "an unclassified exception should mark the span failed"
