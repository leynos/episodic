"""Shared observability ports for tracing, bounded metrics, and monotonic timing.

This package defines the canonical observability ports that adapters and
services across the codebase wire against:

- :class:`MetricsPort` is the canonical metrics interface for new code. Its
  label parameters are typed as ``collections.abc.Mapping[str, str]`` so
  callers can pass either ``dict`` or read-only mapping values, which keeps
  the port aligned with structural typing best practice for input parameters.
- :class:`MonotonicClockPort` is the canonical clock port for measuring
  elapsed operation time. Feature modules (for example
  :mod:`episodic.qa.chrono`) reuse this port directly rather than declaring
  parallel hierarchies.
- :class:`TracerPort` provides synchronous span contexts. The
  :class:`StructuredLogTracer` adapter logs span names and only the safe
  allow-list of ``operation``, ``outcome``, ``failure_category``,
  ``representation``, and ``pagination``; it drops all other attributes
  because callers may attach sensitive operation metadata.

The definitions live in cohesive submodules — ports with their inert
defaults, the structured-log adapters, and the recording test doubles — while
this barrel is the single import surface, so callers keep importing from
:mod:`episodic.observability`.

:class:`episodic.metrics_ports.BoundedMetricsPort` remains a narrower legacy
subtype with ``dict[str, str]`` labels for feature ports such as
:class:`episodic.qa.chrono.ChronoMetricsPort`; adapters satisfying
:class:`MetricsPort` also satisfy it.
"""

from episodic.observability._ports import (
    MetricsPort,
    MonotonicClockPort,
    NoopMetrics,
    NoopTracer,
    NoopValueMetrics,
    PerfCounterClock,
    SpanHandle,
    TracerPort,
    ValueMetricsPort,
)
from episodic.observability._recording import RecordedSpan, RecordingTracer
from episodic.observability._structured import (
    StructuredLogMetrics,
    StructuredLogTracer,
    admits_telemetry,
    configure_structured_logging,
)

__all__ = [
    "MetricsPort",
    "MonotonicClockPort",
    "NoopMetrics",
    "NoopTracer",
    "NoopValueMetrics",
    "PerfCounterClock",
    "RecordedSpan",
    "RecordingTracer",
    "SpanHandle",
    "StructuredLogMetrics",
    "StructuredLogTracer",
    "TracerPort",
    "ValueMetricsPort",
    "admits_telemetry",
    "configure_structured_logging",
]
