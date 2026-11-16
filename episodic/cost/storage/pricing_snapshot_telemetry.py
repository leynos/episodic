"""Report bounded telemetry for pricing-snapshot persistence and reads.

Persistence and verification live in `SqlAlchemyPricingSnapshotStore`; this
decorator adds counters, latency, and spans around any
`PricingSnapshotRepository`. Keeping the two apart means a change to the
observability vocabulary cannot alter how a snapshot is written, and the store
stays usable in tests and scripts without a metrics sink.

The unit of work wraps the store, so application code receives the instrumented
repository as `CanonicalUnitOfWork.pricing_snapshots`.
"""

import dataclasses as dc
import typing as typ

from sqlalchemy.exc import IntegrityError

from episodic import observability
from episodic.cost.pricing_snapshot_ports import (
    EnsuredPricingSnapshot,
    PricingSnapshotIntegrityError,
    PricingSnapshotNotFoundError,
    PricingSnapshotRepository,
)

if typ.TYPE_CHECKING:
    from episodic.cost.pricing_snapshot import PricingSnapshot
    from episodic.cost.primitives import PricingSnapshotId


@dc.dataclass(frozen=True, slots=True)
class _OperationTelemetry:
    """Metric names and bounded operation label for one repository method."""

    counter: str
    latency: str
    operation: str


_ENSURE_TELEMETRY = _OperationTelemetry(
    counter="pricing_snapshot.ensure",
    latency="pricing_snapshot.ensure.duration_ms",
    operation="ensure_snapshot",
)
_GET_TELEMETRY = _OperationTelemetry(
    counter="pricing_snapshot.get",
    latency="pricing_snapshot.get.duration_ms",
    operation="get_snapshot",
)


@dc.dataclass(slots=True)
class _CallReport:
    """Outcome of one repository call, carried from the call to its span."""

    value: str = "error"
    failure_category: str | None = None


class InstrumentedPricingSnapshotRepository:
    """Add counters, latency, and spans to a snapshot repository."""

    def __init__(
        self,
        repository: PricingSnapshotRepository,
        *,
        metrics: observability.MetricsPort | None = None,
        tracer: observability.TracerPort | None = None,
        clock: observability.MonotonicClockPort | None = None,
    ) -> None:
        """Wrap one repository with the runtime telemetry sinks.

        Parameters
        ----------
        repository : PricingSnapshotRepository
            Repository whose calls are measured; it performs no reporting.
        metrics : MetricsPort | None, optional
            Bounded metrics sink. Defaults to ``NoopMetrics``.
        tracer : TracerPort | None, optional
            Span sink for repository operations. Defaults to ``NoopTracer``.
        clock : MonotonicClockPort | None, optional
            Latency measurement clock. Defaults to ``PerfCounterClock``.
        """
        self._repository = repository
        self._metrics: observability.MetricsPort = (
            metrics if metrics is not None else observability.NoopMetrics()
        )
        self._tracer: observability.TracerPort = (
            tracer if tracer is not None else observability.NoopTracer()
        )
        self._clock: observability.MonotonicClockPort = (
            clock if clock is not None else observability.PerfCounterClock()
        )

    def _finish_span(
        self,
        span: observability.SpanHandle,
        telemetry: _OperationTelemetry,
        started: float,
        report: _CallReport,
    ) -> None:
        """Close one span and emit its metrics, whatever the outcome."""
        span.set_attribute("outcome", report.value)
        if report.failure_category is not None:
            span.set_attribute("failure_category", report.failure_category)
        self._record_outcome(telemetry, started, report)

    def _record_outcome(
        self,
        telemetry: _OperationTelemetry,
        started: float,
        report: _CallReport,
    ) -> None:
        """Emit the bounded counter and latency metrics for one operation."""
        labels = {"operation": telemetry.operation, "outcome": report.value}
        if report.failure_category is not None:
            labels["failure_category"] = report.failure_category
        self._metrics.increment_counter(telemetry.counter, labels=labels)
        self._metrics.observe_latency_ms(
            telemetry.latency,
            (self._clock.monotonic_seconds() - started) * 1000.0,
            labels={"operation": telemetry.operation, "outcome": report.value},
        )

    async def ensure(self, snapshot: PricingSnapshot) -> EnsuredPricingSnapshot:
        """Persist a snapshot, reporting its outcome and any failure category.

        Returns
        -------
        EnsuredPricingSnapshot
            Identifier of the stored row and whether this call inserted it.

        Raises
        ------
        PricingSnapshotIntegrityError
            If the insert conflicts without a matching stored content hash.
        sqlalchemy.exc.IntegrityError
            If any constraint other than content-hash uniqueness fails.
        """
        started = self._clock.monotonic_seconds()
        report = _CallReport()
        with self._tracer.start_span(
            "pricing_snapshot.ensure_snapshot",
            attributes={"operation": _ENSURE_TELEMETRY.operation},
        ) as span:
            try:
                ensured = await self._repository.ensure(snapshot)
            except IntegrityError, PricingSnapshotIntegrityError:
                report.failure_category = "pricing_snapshot.integrity"
                raise
            else:
                report.value = ensured.outcome.value
                return ensured
            finally:
                self._finish_span(span, _ENSURE_TELEMETRY, started, report)

    async def get(self, pricing_snapshot_id: PricingSnapshotId) -> PricingSnapshot:
        """Read a stored snapshot, reporting its outcome and failure category.

        Returns
        -------
        PricingSnapshot
            Snapshot rebuilt from the stored row and verified against its hash.

        Raises
        ------
        PricingSnapshotNotFoundError
            If no row is stored for ``pricing_snapshot_id``.
        PricingSnapshotIntegrityError
            If the stored row no longer hashes to its recorded content hash.
        """
        started = self._clock.monotonic_seconds()
        report = _CallReport()
        with self._tracer.start_span(
            "pricing_snapshot.get_snapshot",
            attributes={"operation": _GET_TELEMETRY.operation},
        ) as span:
            try:
                snapshot = await self._repository.get(pricing_snapshot_id)
            except PricingSnapshotNotFoundError:
                report.value = "not_found"
                report.failure_category = "pricing_snapshot.not_found"
                raise
            except PricingSnapshotIntegrityError:
                report.value = "integrity_mismatch"
                report.failure_category = "pricing_snapshot.tampered"
                # The identifier is unbounded and may be sensitive; keep it on
                # the span only, never on a metric label.
                span.set_attribute("pricing_snapshot_id", str(pricing_snapshot_id))
                raise
            else:
                report.value = "found"
                return snapshot
            finally:
                self._finish_span(span, _GET_TELEMETRY, started, report)
