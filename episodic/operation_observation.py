"""One bounded span and latency observation per application operation.

Counters say *what* happened but not *how long* it took and not which operation
was running, so a slow QA write is indistinguishable from a slow database or a
slow network call. This module supplies the operation-level signal: one span per
operation and one latency observation, both carrying bounded labels only.

Attributes that could carry unbounded or sensitive data never reach a span or a
metric. An operation is named from a fixed vocabulary chosen by its caller, and
the labels are bounded values such as an evaluator, an outcome, and a stable
failure category.
"""

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.observability import (
        MetricsPort,
        MonotonicClockPort,
        SpanHandle,
        TracerPort,
    )

UNKNOWN_OUTCOME = "unknown"
UNEXPECTED_FAILURE = "unexpected_error"


@dc.dataclass(slots=True)
class OperationObservation:
    """Time one operation and close its span.

    Parameters
    ----------
    tracer : TracerPort
        Span sink used to mark the operation's start, outcome, and failure.
    metrics : MetricsPort
        Latency sink for the completed operation.
    clock : MonotonicClockPort
        Elapsed-time source. A monotonic clock is required because the
        operation may span a wall-clock adjustment.
    span_name : str
        Stable operation name, such as ``qa_artefact.record`` or
        ``cli.qa_evaluations.list``. The latency metric appends
        ``.latency_ms`` to it.
    labels : collections.abc.Mapping[str, str], optional
        Bounded labels shared by the span and the latency observation, such as
        the evaluator. Values must already be bounded; no payload, identifier,
        or free text belongs here.

    Examples
    --------
    >>> observation = OperationObservation(
    ...     tracer, metrics, clock, "qa_artefact.get", {"evaluator": "pedante"}
    ... )
    >>> with observation:
    ...     observation.succeeded("not_found")
    """

    tracer: TracerPort
    metrics: MetricsPort
    clock: MonotonicClockPort
    span_name: str
    labels: cabc.Mapping[str, str] = dc.field(default_factory=dict)
    outcome: str = UNKNOWN_OUTCOME
    failure_category: str | None = None
    _started_at: float = dc.field(default=0.0, repr=False)
    _span: SpanHandle | None = dc.field(default=None, repr=False)

    def __enter__(self) -> typ.Self:
        """Start the span and record the operation's start time."""
        self._started_at = self.clock.monotonic_seconds()
        scope = self.tracer.start_span(
            self.span_name,
            attributes={"operation": self.span_name},
        )
        self._span = scope.__enter__()
        return self

    def succeeded(self, outcome: str = "success") -> None:
        """Record that the operation completed with ``outcome``."""
        self.outcome = outcome
        if self._span is not None:
            self._span.set_attribute("outcome", outcome)

    def failed(self, category: str) -> None:
        """Record that the operation failed with a bounded ``category``."""
        self.outcome = "failed"
        self.failure_category = category
        if self._span is not None:
            self._span.set_attribute("outcome", "failed")
            self._span.set_attribute("failure_category", category)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        """Emit the latency observation and complete the span."""
        if exc_type is not None and self.outcome == UNKNOWN_OUTCOME:
            # An exception that no branch classified would otherwise read as a
            # successful outcome, so make the unclassified case visible.
            self.failed(UNEXPECTED_FAILURE)
        self._observe_latency()
        if self._span is None:
            return False
        return self._span.__exit__(exc_type, exc_value, traceback)

    def _observe_latency(self) -> None:
        """Emit one bounded latency observation for the operation."""
        elapsed_ms = (self.clock.monotonic_seconds() - self._started_at) * 1000.0
        labels = {**self.labels, "outcome": self.outcome}
        if self.failure_category is not None:
            labels["failure_category"] = self.failure_category
        self.metrics.observe_latency_ms(
            f"{self.span_name}.latency_ms",
            elapsed_ms,
            labels=labels,
        )
