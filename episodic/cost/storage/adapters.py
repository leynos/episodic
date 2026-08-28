"""Persist cost accounting records through SQLAlchemy.

Use this module when a caller already owns an ``AsyncSession`` and wants
database-backed implementations of the cost ledger and metering ports.
``SqlAlchemyCostLedgerStore`` records provider calls and task roll-ups with
idempotency keys. ``SqlAlchemyMeteringCounterStore`` atomically increments
period counters and stores one event per idempotency key.

Callers are responsible for transaction boundaries. Create the adapter inside
the unit of work, call the port method, then commit or roll back the surrounding
session.
"""

import typing as typ
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from episodic.cost._time import parse_instant
from episodic.cost.ports import (
    CostLedgerEntryId,
    LedgerScope,
    PricingModel,
    PricingSnapshot,
    PricingSnapshotCollisionError,
    PricingSnapshotId,
    ProviderCallLedgerEntry,
    RunPricingKey,
    TaskRollupLedgerEntry,
    UsageSource,
)
from episodic.observability import (
    MetricsPort,
    MonotonicClockPort,
    NoopMetrics,
    NoopTracer,
    PerfCounterClock,
    TracerPort,
)

from .models import (
    CostLedgerEntryRecord,
    PricingSnapshotRecord,
    RunPricingPinRecord,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _new_id() -> uuid.UUID:
    """Return a new storage identifier."""
    return uuid.uuid7()


def _optional_entry_id(value: CostLedgerEntryId | None) -> uuid.UUID | None:
    """Convert an optional port identifier to UUID."""
    return None if value is None else uuid.UUID(str(value))


def _provider_call_values(entry: ProviderCallLedgerEntry) -> dict[str, object]:
    """Build storage values for a provider-call ledger row."""
    return {
        "id": _new_id(),
        "idempotency_key": str(entry.idempotency_key),
        "parent_cost_entry_id": _optional_entry_id(entry.parent_cost_entry_id),
        "scope": entry.scope.value,
        "provider_type": entry.provider_type,
        "provider_name": entry.provider_name,
        "workflow_node": entry.workflow_node,
        "operation": entry.operation,
        "pricing_snapshot_id": uuid.UUID(str(entry.pricing_snapshot_id)),
        "usage": dict(entry.usage),
        "usage_source": entry.usage_source.value,
        "usage_complete": entry.usage_complete,
        "computed_cost_minor": entry.computed_cost_minor,
        "currency": str(entry.currency),
        "pricing_model": entry.pricing_model.value,
        "retry_attempt": entry.retry_attempt,
        "billing_period_key": str(entry.billing_period_key),
        "workflow_run_id": entry.workflow_run_id,
        "recorded_at": parse_instant(
            entry.recorded_at,
            error_message="timestamp must include timezone information.",
        ),
    }


def _task_rollup_values(rollup: TaskRollupLedgerEntry) -> dict[str, object]:
    """Build storage values for a task roll-up ledger row."""
    return {
        "id": _new_id(),
        "idempotency_key": str(rollup.idempotency_key),
        "parent_cost_entry_id": None,
        "scope": LedgerScope.TASK.value,
        "provider_type": "internal",
        "provider_name": "episodic",
        "workflow_node": rollup.workflow_node,
        "operation": "task_rollup",
        "pricing_snapshot_id": None,
        "usage": {},
        "usage_source": UsageSource.ROLLUP.value,
        "usage_complete": True,
        "computed_cost_minor": rollup.computed_cost_minor,
        "currency": str(rollup.currency),
        "pricing_model": PricingModel.ROLLUP.value,
        "retry_attempt": 0,
        "billing_period_key": str(rollup.billing_period_key),
        "workflow_run_id": rollup.workflow_run_id,
        "recorded_at": parse_instant(
            rollup.recorded_at,
            error_message="timestamp must include timezone information.",
        ),
    }


class SqlAlchemyCostLedgerStore:
    """SQLAlchemy implementation of `CostLedgerPort`."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        metrics: MetricsPort | None = None,
        tracer: TracerPort | None = None,
        clock: MonotonicClockPort | None = None,
    ) -> None:
        self._session = session
        self._metrics: MetricsPort = metrics if metrics is not None else NoopMetrics()
        self._tracer: TracerPort = tracer if tracer is not None else NoopTracer()
        self._clock: MonotonicClockPort = (
            clock if clock is not None else PerfCounterClock()
        )

    def _record_ensure_outcome(
        self,
        started: float,
        outcome: str,
        failure_category: str | None,
    ) -> None:
        """Emit the bounded ensure-snapshot counter and latency metrics."""
        labels = {"operation": "ensure_snapshot", "outcome": outcome}
        if failure_category is not None:
            labels["failure_category"] = failure_category
        self._metrics.increment_counter("pricing_snapshot.ensure", labels=labels)
        self._metrics.observe_latency_ms(
            "pricing_snapshot.ensure.duration_ms",
            (self._clock.monotonic_seconds() - started) * 1000.0,
            labels={"operation": "ensure_snapshot", "outcome": outcome},
        )

    async def ensure_snapshot(self, snapshot: PricingSnapshot) -> None:
        """Persist an immutable pricing snapshot; reuse an existing row.

        Persists the snapshot identifier, provider name, model, operation,
        source kind, currency, billing period, rates, source metadata,
        content hash, and retrieved-at timestamp. If a row with the same
        ``id`` already exists, the insert is a no-op via
        ``ON CONFLICT DO NOTHING``, leaving the stored row unchanged.

        Raises
        ------
        PricingSnapshotCollisionError
            If ``snapshot.content_hash`` is already stored under a
            different snapshot identifier.
        sqlalchemy.exc.IntegrityError
            If the insert violates a constraint other than the identifier
            or content-hash uniqueness.
        ValueError
            If ``snapshot.retrieved_at`` lacks timezone information, via
            ``parse_instant``'s ``"timestamp must include timezone
            information."`` error.
        """  # noqa: DOC502  # parse_instant raises on the adapter's behalf.
        statement = (
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
        started = self._clock.monotonic_seconds()
        outcome = "error"
        failure_category: str | None = None
        with self._tracer.start_span(
            "pricing_snapshot.ensure_snapshot",
            attributes={"operation": "ensure_snapshot"},
        ) as span:
            try:
                result = await self._session.execute(statement)
            except IntegrityError as exc:
                # The id conflict target does not cover the unique content
                # hash; a duplicate hash under a different identifier is a
                # catalogue defect, not a transient storage failure.
                if "content_hash" in str(exc.orig):
                    outcome, failure_category = (
                        "collision",
                        "pricing_snapshot.collision",
                    )
                    msg = (
                        "pricing snapshot content hash "
                        f"{snapshot.content_hash!r} is already stored under a "
                        "different snapshot identifier"
                    )
                    raise PricingSnapshotCollisionError(msg) from exc
                failure_category = "pricing_snapshot.integrity"
                raise
            else:
                inserted = result.scalar_one_or_none()
                outcome = "persisted" if inserted is not None else "reused"
            finally:
                span.set_attribute("outcome", outcome)
                if failure_category is not None:
                    span.set_attribute("failure_category", failure_category)
                self._record_ensure_outcome(started, outcome, failure_category)

    async def pin_run_pricing(
        self,
        key: RunPricingKey,
        pricing_snapshot_id: PricingSnapshotId,
        pinned_at: str,
    ) -> None:
        """Persist or reuse a run-level pricing pin."""
        statement = (
            insert(RunPricingPinRecord)
            .values(
                workflow_run_id=key.workflow_run_id,
                provider_name=key.provider_name,
                model=key.model,
                operation=key.operation,
                billing_period_key=str(key.billing_period_key),
                pricing_snapshot_id=uuid.UUID(str(pricing_snapshot_id)),
                pinned_at=parse_instant(
                    pinned_at,
                    error_message="timestamp must include timezone information.",
                ),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "workflow_run_id",
                    "provider_name",
                    "model",
                    "operation",
                    "billing_period_key",
                ]
            )
        )
        await self._session.execute(statement)

    async def get_run_pricing_pin(self, key: RunPricingKey) -> PricingSnapshotId | None:
        """Return the pinned pricing snapshot for a run and provider."""
        snapshot_id = (
            await self._session.execute(
                sa.select(RunPricingPinRecord.pricing_snapshot_id).where(
                    RunPricingPinRecord.workflow_run_id == key.workflow_run_id,
                    RunPricingPinRecord.provider_name == key.provider_name,
                    RunPricingPinRecord.model == key.model,
                    RunPricingPinRecord.operation == key.operation,
                    RunPricingPinRecord.billing_period_key
                    == str(key.billing_period_key),
                )
            )
        ).scalar_one_or_none()
        return None if snapshot_id is None else PricingSnapshotId(str(snapshot_id))

    async def sum_provider_call_costs(self, workflow_run_id: str) -> int:
        """Return the total provider-call cost for one workflow run."""
        total = (
            await self._session.execute(
                sa.select(
                    sa.func.coalesce(
                        sa.func.sum(CostLedgerEntryRecord.computed_cost_minor), 0
                    )
                ).where(
                    CostLedgerEntryRecord.workflow_run_id == workflow_run_id,
                    CostLedgerEntryRecord.scope == LedgerScope.PROVIDER_CALL.value,
                )
            )
        ).scalar_one()
        return int(total)

    async def record_call(self, entry: ProviderCallLedgerEntry) -> CostLedgerEntryId:
        """Persist or reuse a provider-call ledger row."""
        return await self._insert_ledger_row(
            _provider_call_values(entry), str(entry.idempotency_key)
        )

    async def record_task_rollup(
        self,
        rollup: TaskRollupLedgerEntry,
    ) -> CostLedgerEntryId:
        """Persist or reuse a task roll-up ledger row."""
        return await self._insert_ledger_row(
            _task_rollup_values(rollup), str(rollup.idempotency_key)
        )

    async def _insert_ledger_row(
        self,
        values: dict[str, object],
        idempotency_key: str,
    ) -> CostLedgerEntryId:
        """Insert a ledger row or return the existing identifier."""
        statement = (
            insert(CostLedgerEntryRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(CostLedgerEntryRecord.id)
        )
        inserted_id = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted_id is not None:
            return CostLedgerEntryId(str(inserted_id))

        existing_id = (
            await self._session.execute(
                sa.select(CostLedgerEntryRecord.id).where(
                    CostLedgerEntryRecord.idempotency_key == idempotency_key
                )
            )
        ).scalar_one()
        return CostLedgerEntryId(str(existing_id))
