"""Provide injectable runtime dependencies for QA artefact storage.

The bundle isolates adapter-owned timestamps, identifiers, and metrics from
SQLAlchemy persistence. Production callers use the default bundle, while tests
may inject deterministic collaborators through the unit of work.
"""

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import uuid

from episodic.observability import (
    MetricsPort,
    MonotonicClockPort,
    NoopMetrics,
    NoopTracer,
    PerfCounterClock,
    TracerPort,
)

type Clock = cabc.Callable[[], dt.datetime]
type UuidFactory = cabc.Callable[[], uuid.UUID]


@dc.dataclass(frozen=True, slots=True)
class QaArtefactStorageRuntime:
    """Runtime providers used by the QA artefact SQLAlchemy adapter.

    Attributes
    ----------
    clock : Clock
        UTC timestamp provider for adapter-assigned storage times.
    uuid_factory : UuidFactory
        Identifier provider shared with the recording service, so artefacts
        and their findings are minted the same way wherever they originate.
    metrics : MetricsPort
        Bounded-cardinality metrics sink for recording outcomes and operation
        latency.
    tracer : TracerPort
        Span sink for one bounded span per repository operation.
    monotonic_clock : MonotonicClockPort
        Elapsed-time source for the operation latency observations.
    """

    clock: Clock
    uuid_factory: UuidFactory
    metrics: MetricsPort
    tracer: TracerPort = dc.field(default_factory=NoopTracer)
    monotonic_clock: MonotonicClockPort = dc.field(default_factory=PerfCounterClock)


def qa_artefact_storage_runtime(
    runtime: QaArtefactStorageRuntime | None,
    *,
    metrics: MetricsPort | None = None,
    tracer: TracerPort | None = None,
    monotonic_clock: MonotonicClockPort | None = None,
) -> QaArtefactStorageRuntime:
    """Return QA artefact providers with production defaults.

    Parameters
    ----------
    runtime : QaArtefactStorageRuntime | None
        Optional injected providers. When supplied they win outright, so a
        caller that needs a fixed clock or identifier sequence also controls
        the observation sinks.
    metrics : MetricsPort | None
        Metrics sink used when no runtime is injected; ``None`` selects the
        no-op sink.
    tracer : TracerPort | None
        Span sink used when no runtime is injected; ``None`` selects the no-op
        tracer.
    monotonic_clock : MonotonicClockPort | None
        Elapsed-time source used when no runtime is injected; ``None`` selects
        the performance-counter clock.

    Returns
    -------
    QaArtefactStorageRuntime
        The supplied runtime, or the production-default provider bundle.
    """
    if runtime is not None:
        return runtime
    return QaArtefactStorageRuntime(
        clock=lambda: dt.datetime.now(dt.UTC),
        uuid_factory=uuid.uuid7,
        metrics=NoopMetrics() if metrics is None else metrics,
        tracer=NoopTracer() if tracer is None else tracer,
        monotonic_clock=(
            PerfCounterClock() if monotonic_clock is None else monotonic_clock
        ),
    )
