"""Structured-log adapters and the logging configuration they depend on.

femtologging's logger registry starts with no handlers, so a structured sink
delivers nothing until the backend is configured. Selecting one of these
adapters therefore requires :func:`configure_structured_logging` first, and
:func:`admits_telemetry` lets a caller stay silent above the level these
adapters emit at.
"""

import dataclasses as dc
import typing as typ

from episodic.logging import (
    LoggerHandle,
    LogLevel,
    configure_logging,
    format_log_event,
    get_logger,
    log_info,
)
from episodic.observability._ports import NoopTracer, NoopValueMetrics

if typ.TYPE_CHECKING:
    from collections import abc as cabc

    from episodic.observability._ports import SpanHandle, TracerPort, ValueMetricsPort

# The structured sinks emit at INFO, so only these levels ask for their records.
_TELEMETRY_LEVELS = frozenset({LogLevel.TRACE, LogLevel.DEBUG, LogLevel.INFO})


def configure_structured_logging(level: str | None) -> LogLevel:
    """Configure the process logger the structured sinks write through.

    femtologging's logger registry starts with no handlers, so a structured
    sink delivers nothing until the backend is configured. A caller that
    selects :class:`StructuredLogTracer` or :class:`StructuredLogMetrics` must
    call this first.

    Parameters
    ----------
    level : str | None
        Requested level; ``None`` selects the logging port's default.

    Returns
    -------
    LogLevel
        The normalized level the backend was configured with.

    Examples
    --------
    >>> configure_structured_logging("INFO")  # doctest: +SKIP
    <LogLevel.INFO: 'INFO'>
    """
    effective, _ = configure_logging(level)
    return effective


def admits_telemetry(level: LogLevel) -> bool:
    """Return whether ``level`` admits the structured observers' records.

    The pinned femtologging backend does not filter records by the configured
    level, so a caller that must stay quiet above ``INFO`` has to decline the
    structured sinks itself rather than rely on the backend.

    Parameters
    ----------
    level : LogLevel
        Level the backend was configured with.

    Returns
    -------
    bool
        ``True`` when the level admits the ``INFO`` records the structured
        sinks emit.
    """
    return level in _TELEMETRY_LEVELS


def _emit_structured_event(
    logger: LoggerHandle,
    event: str,
    /,
    **fields: object,
) -> None:
    """Emit one JSON-encoded observability event through the logging port."""
    log_info(logger, "%s", format_log_event(event, **fields))


@dc.dataclass(frozen=True, slots=True)
class StructuredLogMetrics:
    """Production metrics adapter that emits bounded structured observations."""

    logger: LoggerHandle = dc.field(default_factory=lambda: get_logger(__name__))

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Emit one bounded counter observation."""
        _emit_structured_event(
            self.logger, "metric_counter", metric_name=name, labels=dict(labels)
        )

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Emit one bounded latency observation."""
        self._emit_value("metric_latency", name, value, labels=labels)

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Emit one bounded scalar observation."""
        self._emit_value("metric_value", name, value, labels=labels)

    def _emit_value(
        self,
        event_name: str,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Emit a structured scalar metric event."""
        _emit_structured_event(
            self.logger,
            event_name,
            metric_name=name,
            value=str(value),
            labels=dict(labels),
        )


_SAFE_SPAN_ATTRIBUTES = frozenset({
    "operation",
    "outcome",
    "failure_category",
    "representation",
    "pagination",
})


@dc.dataclass(slots=True)
class _StructuredLogSpan:
    """Complete a structured-log span with allow-listed attributes only."""

    logger: LoggerHandle
    name: str
    attributes: dict[str, str]

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
        _emit_structured_event(
            self.logger,
            event,
            span_name=self.name,
            **self.attributes,
        )
        return False

    def set_attribute(self, name: str, value: str) -> None:
        """Retain an allow-listed bounded operation attribute."""
        if name in _SAFE_SPAN_ATTRIBUTES:
            self.attributes[name] = value


@dc.dataclass(frozen=True, slots=True)
class StructuredLogTracer:
    """Trace adapter that logs safe span lifecycle metadata.

    The adapter logs the event name, span name, and allow-listed bounded
    operation attributes at start and completion. It excludes run identifiers,
    paths, and other sensitive metadata from log records.
    """

    logger: LoggerHandle = dc.field(default_factory=lambda: get_logger(__name__))

    def start_span(
        self,
        name: str,
        *,
        attributes: cabc.Mapping[str, str],
    ) -> SpanHandle:
        """Log a safe span start and return its completion context."""
        safe_attributes = {
            key: value
            for key, value in attributes.items()
            if key in _SAFE_SPAN_ATTRIBUTES
        }
        _emit_structured_event(
            self.logger,
            "trace_span_started",
            span_name=name,
            **safe_attributes,
        )
        return _StructuredLogSpan(
            logger=self.logger,
            name=name,
            attributes=safe_attributes,
        )


def configure_structured_observability(
    level: str | None,
) -> tuple[ValueMetricsPort, TracerPort]:
    """Configure logging and select its matching metrics and trace sinks.

    Parameters
    ----------
    level : str | None
        Requested logging level. Missing or invalid values use the logging
        port's default.

    Returns
    -------
    tuple[ValueMetricsPort, TracerPort]
        Structured sinks when INFO telemetry is enabled, otherwise no-op sinks.
    """
    effective_level = configure_structured_logging(level)
    if admits_telemetry(effective_level):
        return StructuredLogMetrics(), StructuredLogTracer()
    return NoopValueMetrics(), NoopTracer()
