"""Observability ports and the inert defaults used when none is wired.

The protocol definitions are the contract adapters and services share. The
no-op and performance-counter implementations beside them are default sinks
rather than test doubles: they keep an unwired deployment quiet and cheap.
"""

import dataclasses as dc
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


class ValueMetricsPort(MetricsPort, typ.Protocol):
    """Metrics sink that additionally records bounded scalar values."""

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Observe a bounded scalar value."""


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
class NoopValueMetrics(NoopMetrics):
    """Default scalar-metrics sink used when no backend is wired."""

    def observe_value(  # ruff: ignore[no-self-use]  # No-op metrics intentionally retain no state.
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Ignore scalar observations."""
        del name, value, labels


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

    def set_attribute(  # ruff: ignore[no-self-use]  # No-op spans intentionally retain no state.
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

    def start_span(  # ruff: ignore[no-self-use]  # No-op tracer intentionally retains no state.
        self,
        name: str,
        *,
        attributes: cabc.Mapping[str, str],
    ) -> SpanHandle:
        """Return an inert span context."""
        del name, attributes
        return _NOOP_SPAN


@dc.dataclass(frozen=True, slots=True)
class PerfCounterClock:
    """Monotonic clock backed by Python's perf counter."""

    monotonic_seconds: cabc.Callable[[], float] = time.perf_counter
