"""Shared observability ports for tracing, bounded metrics, and monotonic timing.

This module defines the canonical observability ports that adapters and
services across the codebase wire against:

- :class:`MetricsPort` is the canonical metrics interface for new code. Its
  label parameters are typed as ``collections.abc.Mapping[str, str]`` so
  callers can pass either ``dict`` or read-only mapping values, which keeps
  the port aligned with structural typing best practice for input parameters.
- :class:`MonotonicClockPort` is the canonical clock port for measuring
  elapsed operation time. Feature modules (for example
  :mod:`episodic.qa.chrono`) reuse this port directly rather than declaring
  parallel hierarchies.
- :class:`TracerPort` provides synchronous span contexts. Its structured-log
  adapter emits span names but deliberately never logs attributes, because
  callers may attach sensitive operation metadata.

:class:`episodic.metrics_ports.BoundedMetricsPort` is a deliberately narrower
structural subtype with ``dict[str, str]`` labels, retained because feature-
specific ports (such as :class:`episodic.qa.chrono.ChronoMetricsPort`)
historically extend it. Any adapter that satisfies :class:`MetricsPort` also
satisfies :class:`BoundedMetricsPort` for callers that build their label
dicts as concrete ``dict`` instances.
"""

import dataclasses as dc
import logging
import time
import typing as typ

if typ.TYPE_CHECKING:
    from collections import abc as cabc


class MetricsPort(typ.Protocol):
    """Bounded-cardinality metrics sink shared by adapters and services."""

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Increment a bounded-cardinality counter."""

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Observe a latency measurement in milliseconds."""


class SpanHandle(typ.Protocol):
    """Context handle returned when a trace span starts.

    Span handles are synchronous context managers so callers can bound an
    operation with ``with tracer.start_span(...):``.
    """

    def __enter__(self) -> typ.Self:
        """Enter the span context."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        """Complete the span without suppressing an operation exception."""

    def set_attribute(self, name: str, value: str) -> None:
        """Record one bounded operation attribute."""


class TracerPort(typ.Protocol):
    """Trace sink that creates synchronous operation spans.

    Attributes are string mappings so callers can provide ordinary dictionaries
    or read-only mappings. Implementations must treat attributes as sensitive
    operation metadata unless their own storage policy says otherwise.
    """

    def start_span(
        self,
        name: str,
        *,
        attributes: cabc.Mapping[str, str],
    ) -> SpanHandle:
        """Start a span named ``name`` with operation attributes."""


class MonotonicClockPort(typ.Protocol):
    """Clock port for measuring elapsed operation time."""

    def monotonic_seconds(self) -> float:
        """Return a monotonic timestamp in seconds."""


@dc.dataclass(frozen=True, slots=True)
class NoopMetrics:
    """Default metrics sink used when no backend is wired."""

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Ignore counter increments."""

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Ignore latency observations."""


@dc.dataclass(frozen=True, slots=True)
class StructuredLogMetrics:
    """Production metrics adapter that emits bounded structured observations."""

    logger: "_StructuredLogSink" = dc.field(  # noqa: UP037  # Defined below its adapter.
        default_factory=lambda: logging.getLogger(__name__),
    )

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Emit one bounded counter observation."""
        self.logger.info("metric_counter", extra={"metric_name": name, **labels})

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Emit one bounded latency observation."""
        self.logger.info(
            "metric_latency",
            extra={"metric_name": name, "value": str(value), **labels},
        )


@dc.dataclass(frozen=True, slots=True)
class _NoopSpan:
    """Inert span context used by :class:`NoopTracer`."""

    def __enter__(self) -> typ.Self:
        """Enter the inert span context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        """Exit without suppressing an operation exception."""
        del exc_type, exc_value, traceback
        return False

    def set_attribute(  # noqa: PLR6301  # No-op spans intentionally retain no state.
        self,
        name: str,
        value: str,
    ) -> None:
        """Ignore one operation attribute."""
        del name, value


_NOOP_SPAN = _NoopSpan()


@dc.dataclass(frozen=True, slots=True)
class NoopTracer:
    """Default tracer that adds no tracing overhead or side effects."""

    def start_span(  # noqa: PLR6301  # No-op tracer intentionally retains no state.
        self,
        name: str,
        *,
        attributes: cabc.Mapping[str, str],
    ) -> SpanHandle:
        """Return an inert span context."""
        del name, attributes
        return _NOOP_SPAN


class _StructuredLogSink(typ.Protocol):
    """Logger surface required by :class:`StructuredLogTracer`."""

    def info(
        self,
        message: str,
        /,
        *,
        extra: cabc.Mapping[str, str],
    ) -> None:
        """Emit an INFO-level structured event."""


@dc.dataclass(frozen=True, slots=True)
class _StructuredLogSpan:
    """Complete a structured-log span without retaining its attributes."""

    logger: _StructuredLogSink
    name: str

    def __enter__(self) -> typ.Self:
        """Enter the structured-log span context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        """Log completion without suppressing an operation exception."""
        del exc_value, traceback
        event = "trace_span_completed" if exc_type is None else "trace_span_failed"
        self.logger.info(event, extra={"span_name": self.name})
        return False

    def set_attribute(  # noqa: PLR6301  # Structured logging intentionally excludes attributes.
        self,
        name: str,
        value: str,
    ) -> None:
        """Discard operation metadata to keep structured logs non-sensitive."""
        del name, value


@dc.dataclass(frozen=True, slots=True)
class StructuredLogTracer:
    """Trace adapter that logs safe span lifecycle metadata.

    The adapter logs the event name and span name at start and completion. It
    deliberately excludes caller attributes from log records because they may
    contain identifiers, paths, or other sensitive metadata.
    """

    logger: _StructuredLogSink = dc.field(
        default_factory=lambda: logging.getLogger(__name__),
    )

    def start_span(
        self,
        name: str,
        *,
        attributes: cabc.Mapping[str, str],
    ) -> SpanHandle:
        """Log a safe span start and return its completion context."""
        del attributes
        self.logger.info("trace_span_started", extra={"span_name": name})
        return _StructuredLogSpan(logger=self.logger, name=name)


@dc.dataclass(slots=True)
class RecordedSpan:
    """Captured span data exposed by :class:`RecordingTracer` for tests."""

    name: str
    attributes: dict[str, str]
    is_completed: bool = False


@dc.dataclass(slots=True)
class _RecordingSpan:
    """Mark a recorded span complete when its context exits."""

    record: RecordedSpan

    def __enter__(self) -> typ.Self:
        """Enter the recording span context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        """Record completion without suppressing an operation exception."""
        del exc_type, exc_value, traceback
        self.record.is_completed = True
        return False

    def set_attribute(self, name: str, value: str) -> None:
        """Capture one attribute for deterministic assertions."""
        self.record.attributes[name] = value


@dc.dataclass(slots=True)
class RecordingTracer:
    """Test adapter that records spans and their completion state."""

    spans: list[RecordedSpan] = dc.field(default_factory=list)

    def start_span(
        self,
        name: str,
        *,
        attributes: cabc.Mapping[str, str],
    ) -> SpanHandle:
        """Record a span and return its completion context."""
        record = RecordedSpan(name=name, attributes=dict(attributes))
        self.spans.append(record)
        return _RecordingSpan(record)


@dc.dataclass(frozen=True, slots=True)
class PerfCounterClock:
    """Monotonic clock backed by Python's perf counter."""

    monotonic_seconds: cabc.Callable[[], float] = time.perf_counter
