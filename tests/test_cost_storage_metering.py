"""Integration tests for SQLAlchemy metering counters."""

import typing as typ

import pytest
import sqlalchemy as sa

from episodic.cost import BillingPeriodKey, IdempotencyKey, MeteringCounterKey
from episodic.cost.storage import (
    MeteringCounterEventRecord,
    MeteringCounterRecord,
    SqlAlchemyMeteringCounterStore,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_consume_increments_counter_atomically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Metering consumption returns monotone totals for one counter period."""
    async with session_factory() as session:
        store = SqlAlchemyMeteringCounterStore(session)
        first_total = await store.consume(
            MeteringCounterKey("org:1:input_tokens"),
            BillingPeriodKey("2026-06"),
            10,
            IdempotencyKey("meter:1"),
        )
        second_total = await store.consume(
            MeteringCounterKey("org:1:input_tokens"),
            BillingPeriodKey("2026-06"),
            15,
            IdempotencyKey("meter:2"),
        )
        await session.commit()

    assert first_total == 10, f"expected first_total to be 10 but got {first_total}"
    assert second_total == 25, f"expected second_total to be 25 but got {second_total}"


@pytest.mark.asyncio
async def test_consume_reuses_existing_event_for_duplicate_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Duplicate metering idempotency keys do not double-consume."""
    async with session_factory() as session:
        store = SqlAlchemyMeteringCounterStore(session)
        first_total = await store.consume(
            MeteringCounterKey("org:1:output_tokens"),
            BillingPeriodKey("2026-06"),
            20,
            IdempotencyKey("meter:duplicate"),
        )
        second_total = await store.consume(
            MeteringCounterKey("org:1:output_tokens"),
            BillingPeriodKey("2026-06"),
            20,
            IdempotencyKey("meter:duplicate"),
        )
        await session.commit()

    async with session_factory() as session:
        counter_count = (
            await session.execute(
                sa.select(sa.func.count()).select_from(MeteringCounterRecord)
            )
        ).scalar_one()
        event_count = (
            await session.execute(
                sa.select(sa.func.count()).select_from(MeteringCounterEventRecord)
            )
        ).scalar_one()

    assert first_total == 20, f"expected first_total == 20, got {first_total}"
    assert second_total == 20, f"expected second_total == 20, got {second_total}"
    assert counter_count == 1, f"expected counter_count == 1, got {counter_count}"
    assert event_count == 1, f"expected event_count == 1, got {event_count}"


@pytest.mark.asyncio
async def test_consume_rejects_negative_delta(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Negative consumption deltas are invalid at the adapter boundary."""
    async with session_factory() as session:
        store = SqlAlchemyMeteringCounterStore(session)

        with pytest.raises(ValueError, match="delta must be non-negative"):
            await store.consume(
                MeteringCounterKey("org:1:input_tokens"),
                BillingPeriodKey("2026-06"),
                -1,
                IdempotencyKey("meter:negative"),
            )
