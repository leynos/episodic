"""Operation-observation coverage for the QA retrieval CLI.

Each case injects a recording tracer, a metrics sink, and a step clock through
``main`` and pins the single client span the call opens, the bounded outcome it
records, and the latency observation it emits. The HTTP boundary is stubbed, so
the assertions describe the CLI's own instrumentation rather than a server's.
"""

import dataclasses as dc

import httpx
import pytest

from episodic.cli import main
from episodic.cli.client import CliSinks
from episodic.cli.entrypoint import _production_sinks
from episodic.observability import (
    PerfCounterClock,
    RecordedSpan,
    RecordingTracer,
    StructuredLogMetrics,
    StructuredLogTracer,
)
from tests.canonical_storage._workflow_checkpoint_support import (
    RecordingMetrics,
    StepClock,
)
from tests.qa_cli_fixtures import PAGE, canned, list_arguments

pytestmark = pytest.mark.usefixtures("clean_environment")

_SPAN = "cli.qa_evaluations.list"
type _Latency = tuple[str, float, dict[str, str]]


@dc.dataclass(frozen=True, slots=True)
class _Observation:
    """Everything one CLI invocation made visible to the sinks."""

    exit_code: int
    spans: list[RecordedSpan]
    latencies: list[_Latency]


def _observe(transport: httpx.BaseTransport, *arguments: str) -> _Observation:
    """Run the CLI with recording sinks and return its observations."""
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    exit_code = main(
        list(arguments),
        transport=transport,
        sinks=CliSinks(tracer=tracer, metrics=metrics, clock=StepClock()),
    )
    return _Observation(exit_code, tracer.spans, metrics.latencies)


def _expected(
    exit_code: int,
    outcome: str,
    *,
    failure_category: str | None = None,
) -> _Observation:
    """Return the one-span, one-latency observation an outcome should produce."""
    attributes = {"operation": _SPAN, "outcome": outcome}
    labels = {"outcome": outcome}
    if failure_category is not None:
        attributes["failure_category"] = failure_category
        labels["failure_category"] = failure_category
    return _Observation(
        exit_code=exit_code,
        spans=[RecordedSpan(name=_SPAN, attributes=attributes, is_completed=True)],
        latencies=[(f"{_SPAN}.latency_ms", 1.0, labels)],
    )


def test_production_sinks_are_the_structured_log_adapters() -> None:
    """The installed command reports through the structured-log adapters."""
    sinks = _production_sinks()

    assert isinstance(sinks.tracer, StructuredLogTracer), (
        "a production CLI invocation should trace through structured logs"
    )
    assert isinstance(sinks.metrics, StructuredLogMetrics), (
        "a production CLI invocation should report metrics through structured logs"
    )
    assert isinstance(sinks.clock, PerfCounterClock), (
        "a production CLI invocation should time calls with the monotonic clock"
    )


def test_successful_listing_records_one_client_span() -> None:
    """A served page is one successful client span and one latency."""
    transport, _ = canned(PAGE)

    assert _observe(transport, *list_arguments()) == _expected(0, "success"), (
        "a served page should record one successful span"
    )


def test_error_envelope_marks_the_span_failed() -> None:
    """An error envelope is a bounded ``api_error`` failure."""
    transport, _ = canned(
        {"code": "qa_evaluation_not_found", "message": "QA evaluation not found."},
        status=404,
    )

    observed = _observe(transport, *list_arguments())

    assert observed == _expected(1, "failed", failure_category="api_error"), (
        "an error envelope should record an api_error span"
    )


def test_throttled_request_marks_the_span_failed() -> None:
    """A throttle is a bounded ``rate_limited`` failure."""
    transport, _ = canned(
        {"code": "rate_limited", "message": "Too many requests."},
        status=429,
        headers={"Retry-After": "30"},
    )

    observed = _observe(transport, *list_arguments())

    assert observed == _expected(4, "failed", failure_category="rate_limited"), (
        "a throttle should record a rate_limited span"
    )


def test_transport_failure_marks_the_span_failed() -> None:
    """An unreachable API is a bounded ``transport_failure``."""
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(
            httpx.ConnectError("connection refused", request=request)
        )
    )

    observed = _observe(transport, *list_arguments())

    assert observed == _expected(3, "failed", failure_category="transport_failure"), (
        "an unreachable API should record a transport_failure span"
    )


def test_unusable_transport_url_marks_the_span_failed() -> None:
    """A URL only httpx rejects is a bounded ``invalid_url`` failure."""
    transport, recorded = canned(PAGE)

    observed = _observe(
        transport,
        "--base-url",
        "http://api.example.test:not-a-port",
        *list_arguments(),
    )

    assert observed == _expected(2, "failed", failure_category="invalid_url"), (
        "a rejected URL should record an invalid_url span"
    )
    assert recorded.seen == [], "an invalid URL must send no request"
