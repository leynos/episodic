"""Operation-observation coverage for the QA retrieval CLI.

Each case injects a recording tracer, a metrics sink, and a step clock through
``main`` and pins the single client span the call opens, the bounded outcome it
records, and the latency observation it emits. The HTTP boundary is stubbed, so
the assertions describe the CLI's own instrumentation rather than a server's.
"""

import httpx
import pytest

from episodic.cli import main
from episodic.observability import RecordedSpan, RecordingTracer
from tests.canonical_storage._workflow_checkpoint_support import (
    RecordingMetrics,
    StepClock,
)
from tests.qa_cli_fixtures import PAGE, canned, list_arguments

pytestmark = pytest.mark.usefixtures("clean_environment")

_SPAN = "cli.qa_evaluations.list"


def _span(outcome: str, *, failure_category: str | None = None) -> RecordedSpan:
    """Return the completed client span an outcome produces."""
    attributes = {"operation": _SPAN, "outcome": outcome}
    if failure_category is not None:
        attributes["failure_category"] = failure_category
    return RecordedSpan(name=_SPAN, attributes=attributes, is_completed=True)


def _latency(
    outcome: str,
    *,
    failure_category: str | None = None,
) -> tuple[str, float, dict[str, str]]:
    """Return the one-millisecond latency ``StepClock`` produces."""
    labels = {"outcome": outcome}
    if failure_category is not None:
        labels["failure_category"] = failure_category
    return (f"{_SPAN}.latency_ms", 1.0, labels)


def _run(
    transport: httpx.BaseTransport,
    *arguments: str,
) -> tuple[int, RecordingTracer, RecordingMetrics]:
    """Run the CLI with recording sinks and return its observations."""
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    exit_code = main(
        list(arguments),
        transport=transport,
        tracer=tracer,
        metrics=metrics,
        clock=StepClock(),
    )
    return exit_code, tracer, metrics


def test_successful_listing_records_one_client_span(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A served page is one successful client span and one latency."""
    transport, _ = canned(PAGE)

    exit_code, tracer, metrics = _run(transport, *list_arguments())

    capsys.readouterr()
    assert exit_code == 0, "a served page should exit successfully"
    assert tracer.spans == [_span("success")], tracer.spans
    assert metrics.latencies == [_latency("success")], metrics.latencies


def test_error_envelope_marks_the_span_failed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An error envelope is a bounded ``api_error`` failure."""
    transport, _ = canned(
        {"code": "qa_evaluation_not_found", "message": "QA evaluation not found."},
        status=404,
    )

    exit_code, tracer, metrics = _run(transport, *list_arguments())

    capsys.readouterr()
    assert exit_code == 1, "an API error envelope should exit 1"
    assert tracer.spans == [_span("failed", failure_category="api_error")], tracer.spans
    assert metrics.latencies == [_latency("failed", failure_category="api_error")], (
        metrics.latencies
    )


def test_throttled_request_marks_the_span_failed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A throttle is a bounded ``rate_limited`` failure."""
    transport, _ = canned(
        {"code": "rate_limited", "message": "Too many requests."},
        status=429,
        headers={"Retry-After": "30"},
    )

    exit_code, tracer, metrics = _run(transport, *list_arguments())

    capsys.readouterr()
    assert exit_code == 4, "a throttled request should exit 4"
    assert tracer.spans == [_span("failed", failure_category="rate_limited")], (
        tracer.spans
    )
    assert metrics.latencies == [_latency("failed", failure_category="rate_limited")], (
        metrics.latencies
    )


def test_transport_failure_marks_the_span_failed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unreachable API is a bounded ``transport_failure``."""
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(
            httpx.ConnectError("connection refused", request=request)
        )
    )

    exit_code, tracer, metrics = _run(transport, *list_arguments())

    capsys.readouterr()
    assert exit_code == 3, "an unreachable API should exit 3"
    assert tracer.spans == [_span("failed", failure_category="transport_failure")], (
        tracer.spans
    )
    assert metrics.latencies == [
        _latency("failed", failure_category="transport_failure")
    ], metrics.latencies


def test_unusable_transport_url_marks_the_span_failed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A URL only httpx rejects is a bounded ``invalid_url`` failure."""
    transport, recorded = canned(PAGE)

    exit_code, tracer, metrics = _run(
        transport,
        "--base-url",
        "http://api.example.test:not-a-port",
        *list_arguments(),
    )

    capsys.readouterr()
    assert exit_code == 2, "an invalid URL should exit 2"
    assert recorded.seen == [], "an invalid URL must send no request"
    assert tracer.spans == [_span("failed", failure_category="invalid_url")], (
        tracer.spans
    )
    assert metrics.latencies == [_latency("failed", failure_category="invalid_url")], (
        metrics.latencies
    )
