"""Bundle observability ports for adapters that share runtime sinks."""

import dataclasses as dc

from episodic.observability import (
    MetricsPort,
    MonotonicClockPort,
    NoopMetrics,
    NoopTracer,
    PerfCounterClock,
    TracerPort,
)


@dc.dataclass(frozen=True, slots=True)
class ObservabilityRuntime:
    """Runtime bundle for metrics, monotonic timing, and tracing ports.

    Use this bundle at composition seams where several adapters must share
    the same observability sinks. Feature APIs that need only one port should
    continue to accept that port directly.

    Attributes
    ----------
    metrics : MetricsPort
        Bounded metrics sink; defaults to ``NoopMetrics``.
    clock : MonotonicClockPort
        Monotonic clock for elapsed-time measurements; defaults to
        ``PerfCounterClock``.
    tracer : TracerPort
        Span sink; defaults to ``NoopTracer``.
    """

    metrics: MetricsPort = dc.field(default_factory=NoopMetrics)
    clock: MonotonicClockPort = dc.field(default_factory=PerfCounterClock)
    tracer: TracerPort = dc.field(default_factory=NoopTracer)
