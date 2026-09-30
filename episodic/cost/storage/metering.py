"""Persist metering counters through SQLAlchemy.

``SqlAlchemyMeteringCounterStore`` atomically increments period counters and
stores one event per idempotency key. Callers own transaction boundaries, as
for the sibling ledger adapter in ``adapters``.
"""

import typing as typ

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from .models import (
    MeteringCounterEventRecord,
    MeteringCounterRecord,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.cost.ports import (
        BillingPeriodKey,
        IdempotencyKey,
        MeteringCounterKey,
    )


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
