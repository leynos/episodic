"""Persist and read immutable pricing snapshots through SQLAlchemy.

Use `SqlAlchemyPricingSnapshotStore` inside the canonical unit of work. It
implements `PricingSnapshotRepository`: ``ensure`` inserts a snapshot without
ever rewriting an existing row, keyed by its canonical content hash, and
``get`` rebuilds the snapshot a pinned run was priced from and verifies that
the stored row still hashes to its recorded identity.

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
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    SourceDocument,
    UsageUnit,
)
from episodic.cost.pricing_snapshot_hash import canonical_rates
from episodic.cost.pricing_snapshot_ports import (
    EnsuredPricingSnapshot,
    PricingSnapshotIntegrityError,
    PricingSnapshotNotFoundError,
    SnapshotEnsureOutcome,
)
from episodic.cost.primitives import (
    CurrencyCode,
    PricingSnapshotId,
    PricingSourceKind,
)

from .models import PricingSnapshotRecord

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.dml import Insert

_CONTENT_HASH_CONSTRAINT = "uq_pricing_snapshots_content_hash"


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


def _snapshot_insert_statement(
    snapshot: PricingSnapshot,
    pricing_snapshot_id: PricingSnapshotId,
) -> Insert:
    """Build the content-addressed insert statement for one snapshot."""
    document = snapshot.source_document
    return (
        insert(PricingSnapshotRecord)
        .values(
            id=uuid.UUID(str(pricing_snapshot_id)),
            schema_version=snapshot.schema_version,
            service_kind=str(snapshot.service_kind),
            provider_name=snapshot.provider_name,
            model=snapshot.model,
            operation=snapshot.operation,
            source_kind=str(snapshot.source_kind),
            currency=str(snapshot.currency),
            rates=canonical_rates(snapshot.rates),
            source_metadata=dict(snapshot.source_metadata),
            retrieved_at=snapshot.retrieved_at,
            effective_from=snapshot.effective_from,
            source_document_media_type=(
                None if document is None else document.media_type
            ),
            source_document_content=None if document is None else document.content,
            content_hash=snapshot.content_hash,
        )
        .on_conflict_do_nothing(constraint=_CONTENT_HASH_CONSTRAINT)
        .returning(PricingSnapshotRecord.id)
    )


def _rates_from_record(record: PricingSnapshotRecord) -> dict[str, MeteredRate]:
    """Rebuild exact rates from their stored representation."""
    raw_rates = typ.cast("dict[str, dict[str, object]]", dict(record.rates))
    return {
        metric: MeteredRate(
            typ.cast("int", rate["amount_minor"]),
            typ.cast("int", rate["per_units"]),
            UsageUnit(typ.cast("str", rate["unit"])),
        )
        for metric, rate in raw_rates.items()
    }


def _source_document_from_record(
    record: PricingSnapshotRecord,
) -> SourceDocument | None:
    """Rebuild an optional verbatim source document."""
    if (
        record.source_document_media_type is None
        or record.source_document_content is None
    ):
        return None
    return SourceDocument(
        media_type=record.source_document_media_type,
        content=record.source_document_content,
    )


def _snapshot_from_record(record: PricingSnapshotRecord) -> PricingSnapshot:
    """Rebuild the domain snapshot from its stored row."""
    return PricingSnapshot(
        service_kind=PricedService(record.service_kind),
        provider_name=record.provider_name,
        model=record.model,
        operation=record.operation,
        source_kind=PricingSourceKind(record.source_kind),
        currency=CurrencyCode(record.currency),
        rates=_rates_from_record(record),
        source_metadata=typ.cast("dict[str, str]", dict(record.source_metadata)),
        retrieved_at=record.retrieved_at,
        effective_from=record.effective_from,
        source_document=_source_document_from_record(record),
        schema_version=record.schema_version,
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
        PricingSnapshotIntegrityError
            If the insert conflicts without a matching stored content hash.
        sqlalchemy.exc.IntegrityError
            If any constraint other than content-hash uniqueness fails.
        """
        # Statement construction is CPU-only and must not inflate the
        # persistence latency operators use to spot database trouble.
        statement = _snapshot_insert_statement(
            snapshot,
            PricingSnapshotId(str(uuid.uuid7())),
        )
        started = self._clock.monotonic_seconds()
        outcome = "error"
        failure_category: str | None = None
        with self._tracer.start_span(
            "pricing_snapshot.ensure_snapshot",
            attributes={"operation": _ENSURE_TELEMETRY.operation},
        ) as span:
            try:
                ensured = await self._ensure_snapshot(snapshot, statement)
            except IntegrityError, PricingSnapshotIntegrityError:
                failure_category = "pricing_snapshot.integrity"
                raise
            else:
                outcome = ensured.outcome.value
                return ensured
            finally:
                span.set_attribute("outcome", outcome)
                if failure_category is not None:
                    span.set_attribute("failure_category", failure_category)
                self._record_outcome(
                    _ENSURE_TELEMETRY,
                    started,
                    outcome,
                    failure_category,
                )

    async def _ensure_snapshot(
        self,
        snapshot: PricingSnapshot,
        statement: Insert,
    ) -> EnsuredPricingSnapshot:
        """Insert the snapshot, or return the row with the same content hash."""
        inserted_id = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted_id is not None:
            return EnsuredPricingSnapshot(
                pricing_snapshot_id=PricingSnapshotId(str(inserted_id)),
                outcome=SnapshotEnsureOutcome.PERSISTED,
            )
        # The integrity check must judge the stored row, not a copy the
        # session already holds: `populate_existing` refreshes loaded
        # attributes from this statement's rows.
        stored = (
            await self._session.execute(
                sa
                .select(PricingSnapshotRecord)
                .where(PricingSnapshotRecord.content_hash == snapshot.content_hash)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if stored is None:
            msg = (
                "pricing snapshot insert conflicted without an existing "
                f"content hash {snapshot.content_hash!r}"
            )
            raise PricingSnapshotIntegrityError(msg)
        # Reusing an identifier hands it to a ledger row that will be read back
        # later, so the row must still hash to the content it claims. A row
        # edited without updating its hash would otherwise be pinned and only
        # fail on a later read, after the cost was already recorded.
        self._verified_snapshot(stored)
        return EnsuredPricingSnapshot(
            pricing_snapshot_id=PricingSnapshotId(str(stored.id)),
            outcome=SnapshotEnsureOutcome.REUSED,
        )

    async def get(self, pricing_snapshot_id: PricingSnapshotId) -> PricingSnapshot:
        """Return the stored snapshot for one identifier.

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
            except PricingSnapshotIntegrityError:
                outcome = "integrity_mismatch"
                failure_category = "pricing_snapshot.tampered"
                # The identifier is unbounded and may be sensitive; keep it on
                # the span only, never on a metric label.
                span.set_attribute("pricing_snapshot_id", str(pricing_snapshot_id))
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
        self,
        pricing_snapshot_id: PricingSnapshotId,
    ) -> PricingSnapshot:
        """Load one stored row, verifying its content hash."""
        try:
            row_id = uuid.UUID(str(pricing_snapshot_id))
        except ValueError:
            msg = f"No pricing snapshot found for id {pricing_snapshot_id}."
            raise PricingSnapshotNotFoundError(msg) from None
        # A read must not flush pending writes: the caller may be mid-transaction
        # and an implicit flush here would persist unrelated work. Refreshing
        # loaded attributes keeps the verification on the stored row rather
        # than a possibly stale copy the session already holds.
        with self._session.no_autoflush:
            record = (
                await self._session.execute(
                    sa
                    .select(PricingSnapshotRecord)
                    .where(PricingSnapshotRecord.id == row_id)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
        if record is None:
            msg = f"No pricing snapshot found for id {pricing_snapshot_id}."
            raise PricingSnapshotNotFoundError(msg)
        return self._verified_snapshot(record)

    @staticmethod
    def _verified_snapshot(record: PricingSnapshotRecord) -> PricingSnapshot:
        """Rebuild a row and refuse it when its content no longer matches."""
        try:
            snapshot = _snapshot_from_record(record)
        except (KeyError, TypeError, ValueError) as exc:
            msg = (
                "stored pricing snapshot content no longer matches its content "
                f"hash: {exc}"
            )
            raise PricingSnapshotIntegrityError(msg) from exc
        if snapshot.content_hash != record.content_hash:
            msg = "stored pricing snapshot content no longer matches its content hash."
            raise PricingSnapshotIntegrityError(msg)
        return snapshot
