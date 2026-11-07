"""Shared helpers for QA artefact storage observability tests.

One definition of the instrumented runtime and of the span and latency shapes
keeps the record, get, and list suites asserting against the same observation
contract.
"""

import datetime as dt
import uuid

from episodic.canonical.storage import QaArtefactStorageRuntime
from episodic.observability import RecordedSpan, RecordingTracer
from tests.canonical_storage._workflow_checkpoint_support import (
    RecordingMetrics,
    StepClock,
)

NOW = dt.datetime(2026, 10, 31, 9, 0, tzinfo=dt.UTC)


def instrumented_runtime(
    tracer: RecordingTracer,
    metrics: RecordingMetrics,
) -> QaArtefactStorageRuntime:
    """Return a storage runtime whose operations report to the test sinks."""
    return QaArtefactStorageRuntime(
        clock=lambda: NOW,
        uuid_factory=uuid.uuid7,
        metrics=metrics,
        tracer=tracer,
        monotonic_clock=StepClock(),
    )


def expected_span(
    name: str,
    outcome: str,
    *,
    failure_category: str | None = None,
) -> RecordedSpan:
    """Return the completed span an operation with ``outcome`` records."""
    attributes = {"operation": name, "outcome": outcome}
    if failure_category is not None:
        attributes["failure_category"] = failure_category
    return RecordedSpan(name=name, attributes=attributes, is_completed=True)


def expected_latency(
    name: str,
    labels: dict[str, str],
    value: float = 1.0,
) -> tuple[str, float, dict[str, str]]:
    """Return a latency observation with the millisecond count ``StepClock`` made."""
    return (f"{name}.latency_ms", value, labels)
