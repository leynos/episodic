"""Persist and read immutable pricing snapshots through SQLAlchemy.

Use `SqlAlchemyPricingSnapshotStore` inside the canonical unit of work. It
implements `PricingSnapshotRepository`: ``ensure`` inserts a snapshot without
ever rewriting an existing row, and ``get`` rebuilds the snapshot a pinned run
was priced from.

Callers own the transaction boundary; create the store with an open
``AsyncSession``, call the port method, then commit or roll back.

Examples
--------
Store the snapshot a run pins, then read it back by identifier:

>>> store = SqlAlchemyPricingSnapshotStore(session)
>>> ensured = await store.ensure(snapshot)
>>> stored = await store.get(ensured.pricing_snapshot_id)
"""

import dataclasses as dc
import typing as typ
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from episodic import observability
from episodic.cost._time import parse_instant
from episodic.cost.ports import PricingSnapshot, PricingSnapshotCollisionError
from episodic.cost.pricing_snapshot_ports import (
    EnsuredPricingSnapshot,
    PricingSnapshotNotFoundError,
    SnapshotEnsureOutcome,
)
from episodic.cost.primitives import (
    BillingPeriodKey,
    CurrencyCode,
    PricingSnapshotId,
    PricingSourceKind,
)

from .models import PricingSnapshotRecord

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.dml import Insert

_PRICING_SNAPSHOT_CONTENT_HASH_CONSTRAINT = "uq_pricing_snapshots_content_hash"


@dc.dataclass(frozen=True, slots=True)
class _OperationTelemetry:
    """Metric names and bounded operation label for one store method."""

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


def _is_pricing_snapshot_hash_collision(exc: IntegrityError) -> bool:
    """Identify a duplicate pricing snapshot through its named constraint."""
    # Keep driver inspection local: canonical storage's package initializer
    # composes this adapter, so importing its helper would create an import cycle.
    name: str | None = None
    for candidate in (exc, exc.orig):
        name = getattr(candidate, "constraint_name", None)
        if name is None:
            diagnostic = getattr(candidate, "diag", None)
            name = getattr(diagnostic, "constraint_name", None)
        if name is not None:
            break
    if name is not None:
        return name == _PRICING_SNAPSHOT_CONTENT_HASH_CONSTRAINT
    # Some DB-API wrappers omit diagnostics; match only PostgreSQL's exact
    # duplicate-constraint form so unrelated content_hash errors stay visible.
    return (
        f'violates unique constraint "{_PRICING_SNAPSHOT_CONTENT_HASH_CONSTRAINT}"'
        in str(exc.orig)
    )


def _snapshot_insert_statement(snapshot: PricingSnapshot) -> Insert:
    """Build the idempotent insert statement for one pricing snapshot."""
    return (
        insert(PricingSnapshotRecord)
        .values(
            id=uuid.UUID(str(snapshot.pricing_snapshot_id)),
            provider_name=snapshot.provider_name,
            model=snapshot.model,
            operation=snapshot.operation,
            source_kind=str(snapshot.source_kind),
            currency=str(snapshot.currency),
            billing_period_key=str(snapshot.billing_period_key),
            rates_minor_per_metric=dict(snapshot.rates_minor_per_metric),
            source_metadata=dict(snapshot.source_metadata),
            content_hash=snapshot.content_hash,
            retrieved_at=parse_instant(
                snapshot.retrieved_at,
                error_message="timestamp must include timezone information.",
            ),
            effective_from=snapshot.effective_from,
        )
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(PricingSnapshotRecord.id)
    )


def _snapshot_from_record(record: PricingSnapshotRecord) -> PricingSnapshot:
    """Rebuild the domain snapshot from its stored row."""
    return PricingSnapshot(
        pricing_snapshot_id=PricingSnapshotId(str(record.id)),
        provider_name=record.provider_name,
        model=record.model,
        operation=record.operation,
        source_kind=PricingSourceKind(record.source_kind),
        currency=CurrencyCode(record.currency),
        billing_period_key=BillingPeriodKey(record.billing_period_key),
        rates_minor_per_metric=typ.cast(
            "dict[str, int]", dict(record.rates_minor_per_metric)
        ),
        source_metadata=typ.cast("dict[str, str]", dict(record.source_metadata)),
        content_hash=record.content_hash,
        retrieved_at=record.retrieved_at.isoformat(),
        effective_from=record.effective_from,
    )


class SqlAlchemyPricingSnapshotStore:
    """SQLAlchemy implementation of `PricingSnapshotRepository`."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        metrics: observability.MetricsPort | None = None,
        tracer: observability.TracerPort | None = None,
        clock: observability.MonotonicClockPort | None = None,
    ) -> None:
        """Create a snapshot store bound to one session.

        Parameters
        ----------
        session : AsyncSession
            Session that owns the transaction boundary; the caller commits.
        metrics : MetricsPort | None, optional
            Bounded metrics sink. Defaults to ``NoopMetrics``.
        tracer : TracerPort | None, optional
            Span sink for storage operations. Defaults to ``NoopTracer``.
        clock : MonotonicClockPort | None, optional
            Latency measurement clock. Defaults to ``PerfCounterClock``.
        """
        self._session = session
        self._metrics: observability.MetricsPort = (
            metrics if metrics is not None else observability.NoopMetrics()
        )
        self._tracer: observability.TracerPort = (
            tracer if tracer is not None else observability.NoopTracer()
        )
        self._clock: observability.MonotonicClockPort = (
            clock if clock is not None else observability.PerfCounterClock()
        )

    def _record_outcome(
        self,
        telemetry: _OperationTelemetry,
        started: float,
        outcome: str,
        failure_category: str | None,
    ) -> None:
        """Emit the bounded counter and latency metrics for one operation."""
        labels = {"operation": telemetry.operation, "outcome": outcome}
        if failure_category is not None:
            labels["failure_category"] = failure_category
        self._metrics.increment_counter(telemetry.counter, labels=labels)
        self._metrics.observe_latency_ms(
            telemetry.latency,
            (self._clock.monotonic_seconds() - started) * 1000.0,
            labels={"operation": telemetry.operation, "outcome": outcome},
        )

    async def ensure(self, snapshot: PricingSnapshot) -> EnsuredPricingSnapshot:
        """Persist immutable snapshot values; reuse an existing row unchanged.

        Returns
        -------
        EnsuredPricingSnapshot
            Identifier of the stored row and whether this call inserted it.

        Raises
        ------
        PricingSnapshotCollisionError
            If ``snapshot.content_hash`` is stored under a different identifier.
        sqlalchemy.exc.IntegrityError
            If a constraint other than identifier or content-hash uniqueness fails.
        ValueError
            If ``snapshot.retrieved_at`` lacks a timezone; ``parse_instant`` raises
            ``"timestamp must include timezone information."``.
        """  # ruff: ignore[docstring-extraneous-exception]  # parse_instant raises on the adapter's behalf.
        try:
            statement = _snapshot_insert_statement(snapshot)
        except ValueError:
            labels = {
                "operation": _ENSURE_TELEMETRY.operation,
                "outcome": "error",
                "failure_category": "pricing_snapshot.input_invalid",
            }
            with self._tracer.start_span(
                "pricing_snapshot.input_validation", attributes=labels
            ):
                self._metrics.increment_counter(
                    "pricing_snapshot.input_validation", labels=labels
                )
                raise
        outcome = await self._record_snapshot_insert(snapshot, statement)
        return EnsuredPricingSnapshot(
            pricing_snapshot_id=snapshot.pricing_snapshot_id,
            outcome=outcome,
        )

    async def _record_snapshot_insert(
        self,
        snapshot: PricingSnapshot,
        statement: Insert,
    ) -> SnapshotEnsureOutcome:
        """Instrument snapshot persistence while preserving its outcome."""
        started = self._clock.monotonic_seconds()
        outcome = "error"
        failure_category: str | None = None
        with self._tracer.start_span(
            "pricing_snapshot.ensure_snapshot",
            attributes={"operation": _ENSURE_TELEMETRY.operation},
        ) as span:
            try:
                ensure_outcome = await self._persist_snapshot(snapshot, statement)
            except PricingSnapshotCollisionError:
                outcome = "collision"
                failure_category = "pricing_snapshot.collision"
                raise
            except IntegrityError:
                failure_category = "pricing_snapshot.integrity"
                raise
            else:
                outcome = ensure_outcome.value
                return ensure_outcome
            finally:
                span.set_attribute("outcome", outcome)
                if failure_category is not None:
                    span.set_attribute("failure_category", failure_category)
                self._record_outcome(
                    _ENSURE_TELEMETRY, started, outcome, failure_category
                )

    async def _persist_snapshot(
        self,
        snapshot: PricingSnapshot,
        statement: Insert,
    ) -> SnapshotEnsureOutcome:
        """Insert or reuse a row, translating content-hash collisions."""
        try:
            result = await self._session.execute(statement)
        except IntegrityError as exc:
            # The id conflict target excludes unique content hashes: a duplicate
            # hash under another ID is a catalogue defect.
            if not _is_pricing_snapshot_hash_collision(exc):
                raise
            msg = (
                "pricing snapshot content hash "
                f"{snapshot.content_hash!r} is already stored under a "
                "different snapshot identifier"
            )
            raise PricingSnapshotCollisionError(msg) from exc
        if result.scalar_one_or_none() is not None:
            return SnapshotEnsureOutcome.PERSISTED
        return SnapshotEnsureOutcome.REUSED

    async def get(self, pricing_snapshot_id: PricingSnapshotId) -> PricingSnapshot:
        """Return the stored snapshot for one identifier.

        Returns
        -------
        PricingSnapshot
            Snapshot rebuilt from the stored row.

        Raises
        ------
        PricingSnapshotNotFoundError
            If no row is stored for ``pricing_snapshot_id``.
        """
        started = self._clock.monotonic_seconds()
        outcome = "error"
        failure_category: str | None = None
        with self._tracer.start_span(
            "pricing_snapshot.get_snapshot",
            attributes={"operation": _GET_TELEMETRY.operation},
        ) as span:
            try:
                snapshot = await self._load_snapshot(pricing_snapshot_id)
            except PricingSnapshotNotFoundError:
                outcome = "not_found"
                failure_category = "pricing_snapshot.not_found"
                raise
            else:
                outcome = "found"
                return snapshot
            finally:
                span.set_attribute("outcome", outcome)
                if failure_category is not None:
                    span.set_attribute("failure_category", failure_category)
                self._record_outcome(_GET_TELEMETRY, started, outcome, failure_category)

    async def _load_snapshot(
        self, pricing_snapshot_id: PricingSnapshotId
    ) -> PricingSnapshot:
        """Load one stored row or raise when it is absent."""
        record = (
            await self._session.execute(
                sa.select(PricingSnapshotRecord).where(
                    PricingSnapshotRecord.id == uuid.UUID(str(pricing_snapshot_id))
                )
            )
        ).scalar_one_or_none()
        if record is None:
            msg = f"No pricing snapshot found for id {pricing_snapshot_id}."
            raise PricingSnapshotNotFoundError(msg)
        return _snapshot_from_record(record)
