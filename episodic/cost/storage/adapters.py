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

from episodic.cost._time import parse_instant
from episodic.cost.ports import (
    BillingPeriodKey,
    CostLedgerEntryId,
    IdempotencyKey,
    LedgerScope,
    MeteringCounterKey,
    PricingModel,
    ProviderCallLedgerEntry,
    TaskRollupLedgerEntry,
    UsageSource,
)

from .models import (
    CostLedgerEntryRecord,
    MeteringCounterEventRecord,
    MeteringCounterRecord,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _new_id() -> uuid.UUID:
    """Return a new storage identifier."""
    return uuid.uuid7()


def _optional_entry_id(value: CostLedgerEntryId | None) -> uuid.UUID | None:
    """Convert an optional port identifier to UUID."""
    return None if value is None else uuid.UUID(str(value))


class SqlAlchemyCostLedgerStore:
    """SQLAlchemy implementation of `CostLedgerPort`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_call(self, entry: ProviderCallLedgerEntry) -> CostLedgerEntryId:
        """Persist or reuse a provider-call ledger row."""
        values: dict[str, object] = {
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
        return await self._insert_ledger_row(values, str(entry.idempotency_key))

    async def record_task_rollup(
        self,
        rollup: TaskRollupLedgerEntry,
    ) -> CostLedgerEntryId:
        """Persist or reuse a task roll-up ledger row."""
        values: dict[str, object] = {
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
        return await self._insert_ledger_row(values, str(rollup.idempotency_key))

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


class SqlAlchemyMeteringCounterStore:
    """SQLAlchemy implementation of `MeteringPort`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # Atomic consumption needs the counter, period, delta, and idempotency
    # fields separately to satisfy the storage port without a lossy DTO.
    async def consume(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        counter_key: MeteringCounterKey,
        billing_period_key: BillingPeriodKey,
        delta: int,
        idempotency_key: IdempotencyKey,
    ) -> int:
        """Atomically consume a metering delta."""
        if delta < 0:
            msg = "delta must be non-negative."
            raise ValueError(msg)

        inserted_event = await self._insert_metering_event(
            counter_key,
            billing_period_key,
            delta,
            idempotency_key,
        )
        if not inserted_event:
            return await self._existing_event_total(idempotency_key)

        total = await self._upsert_counter(counter_key, billing_period_key, delta)
        await self._set_event_total(idempotency_key, total)
        return total

    # Keep the event insert aligned with the public consume fields so the
    # idempotency gate cannot drift from the counter mutation.
    async def _insert_metering_event(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        counter_key: MeteringCounterKey,
        billing_period_key: BillingPeriodKey,
        delta: int,
        idempotency_key: IdempotencyKey,
    ) -> bool:
        """Insert the idempotency event that gates counter mutation."""
        statement = (
            insert(MeteringCounterEventRecord)
            .values(
                idempotency_key=str(idempotency_key),
                counter_key=str(counter_key),
                billing_period_key=str(billing_period_key),
                delta=delta,
                consumed_after=0,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(MeteringCounterEventRecord.idempotency_key)
        )
        inserted_key = (await self._session.execute(statement)).scalar_one_or_none()
        return inserted_key is not None

    async def _existing_event_total(self, idempotency_key: IdempotencyKey) -> int:
        """Return an existing idempotent event total, if present."""
        return (
            await self._session.execute(
                sa.select(MeteringCounterEventRecord.consumed_after).where(
                    MeteringCounterEventRecord.idempotency_key == str(idempotency_key)
                )
            )
        ).scalar_one()

    async def _set_event_total(
        self,
        idempotency_key: IdempotencyKey,
        total: int,
    ) -> None:
        """Store the counter total produced by the winning event insert."""
        await self._session.execute(
            sa
            .update(MeteringCounterEventRecord)
            .where(MeteringCounterEventRecord.idempotency_key == str(idempotency_key))
            .values(consumed_after=total)
        )

    async def _upsert_counter(
        self,
        counter_key: MeteringCounterKey,
        billing_period_key: BillingPeriodKey,
        delta: int,
    ) -> int:
        """Increment a counter row and return its consumed total."""
        statement = (
            insert(MeteringCounterRecord)
            .values(
                counter_key=str(counter_key),
                billing_period_key=str(billing_period_key),
                consumed=delta,
            )
            .on_conflict_do_update(
                index_elements=["counter_key", "billing_period_key"],
                set_={
                    "consumed": MeteringCounterRecord.consumed + delta,
                    "updated_at": sa.func.now(),
                },
            )
            .returning(MeteringCounterRecord.consumed)
        )
        return (await self._session.execute(statement)).scalar_one()
