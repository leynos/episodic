"""Concurrency and cancellation coverage for snapshot persistence."""

import asyncio
import contextlib
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.cost import (
    BillingPeriodKey,
    CurrencyCode,
    PricingSnapshot,
    PricingSnapshotId,
    PricingSourceKind,
    RunPricingKey,
)
from episodic.cost.storage import (
    PricingSnapshotRecord,
    RunPricingPinRecord,
    SqlAlchemyCostLedgerStore,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:  # pragma: no cover - runtime alias for evaluated test annotations.
    type SessionFactory = object


def _snapshot(snapshot_id: str) -> PricingSnapshot:
    """Build a deterministic snapshot for concurrency scenarios."""
    return PricingSnapshot(
        pricing_snapshot_id=PricingSnapshotId(snapshot_id),
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        billing_period_key=BillingPeriodKey("2026-06"),
        rates_minor_per_metric={"input_tokens": 100, "output_tokens": 200},
        source_metadata={"source": "concurrency-test"},
        content_hash=f"hash-{snapshot_id}",
        retrieved_at="2026-06-04T09:00:00Z",
    )


def _pin_key(run_id: str) -> RunPricingKey:
    """Build the pricing pin key for one workflow run."""
    return RunPricingKey(
        workflow_run_id=run_id,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        billing_period_key=BillingPeriodKey("2026-06"),
    )


async def _snapshot_row_count(
    session_factory: SessionFactory,
    snapshot_id: str,
) -> int:
    """Count persisted snapshot rows through a fresh session."""
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(sa.func.count(PricingSnapshotRecord.id)).where(
                    PricingSnapshotRecord.id == uuid.UUID(snapshot_id)
                )
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_concurrent_ensure_persists_exactly_one_snapshot(
    session_factory: SessionFactory,
) -> None:
    """Two sessions ensuring one snapshot leave exactly one immutable row."""
    snapshot_id = str(uuid.uuid7())
    snapshot = _snapshot(snapshot_id)
    start = asyncio.Event()

    async def ensure_once() -> None:
        async with session_factory() as session:
            await start.wait()
            await SqlAlchemyCostLedgerStore(session).ensure_snapshot(snapshot)
            await session.commit()

    tasks = [asyncio.create_task(ensure_once()), asyncio.create_task(ensure_once())]
    start.set()
    await asyncio.gather(*tasks)

    assert await _snapshot_row_count(session_factory, snapshot_id) == 1, (
        "concurrent ensures must persist exactly one snapshot row"
    )
    async with session_factory() as session:
        stored_hash = (
            await session.execute(
                sa.select(PricingSnapshotRecord.content_hash).where(
                    PricingSnapshotRecord.id == uuid.UUID(snapshot_id)
                )
            )
        ).scalar_one()
    assert stored_hash == snapshot.content_hash, (
        "the surviving row must carry the first committed snapshot's values"
    )


@pytest.mark.asyncio
async def test_concurrent_ensure_and_pin_persist_one_snapshot_and_pin(
    session_factory: SessionFactory,
) -> None:
    """Two sessions racing ensure-then-pin leave one snapshot and one pin."""
    snapshot_id = str(uuid.uuid7())
    snapshot = _snapshot(snapshot_id)
    run_id = f"run-{snapshot_id}"
    key = _pin_key(run_id)
    start = asyncio.Event()

    async def ensure_and_pin() -> None:
        async with session_factory() as session:
            await start.wait()
            store = SqlAlchemyCostLedgerStore(session)
            await store.ensure_snapshot(snapshot)
            await store.pin_run_pricing(
                key,
                snapshot.pricing_snapshot_id,
                "2026-06-04T10:00:00Z",
            )
            await session.commit()

    tasks = [
        asyncio.create_task(ensure_and_pin()),
        asyncio.create_task(ensure_and_pin()),
    ]
    start.set()
    await asyncio.gather(*tasks)

    assert await _snapshot_row_count(session_factory, snapshot_id) == 1, (
        "concurrent ensure-and-pin must persist exactly one snapshot row"
    )
    async with session_factory() as session:
        pins = (
            (
                await session.execute(
                    sa.select(RunPricingPinRecord).where(
                        RunPricingPinRecord.workflow_run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(pins) == 1, "concurrent pinning must persist exactly one pin row"
    assert str(pins[0].pricing_snapshot_id) == snapshot_id, (
        "the surviving pin must reference the ensured snapshot"
    )


@pytest.mark.asyncio
async def test_cancelled_transaction_leaves_no_partial_snapshot(
    session_factory: SessionFactory,
) -> None:
    """Cancellation before commit rolls back; a retry then succeeds."""
    snapshot_id = str(uuid.uuid7())
    snapshot = _snapshot(snapshot_id)
    run_id = f"run-{snapshot_id}"
    key = _pin_key(run_id)
    ensured = asyncio.Event()
    release = asyncio.Event()

    async def ensure_then_stall() -> None:
        async with session_factory() as session:
            await SqlAlchemyCostLedgerStore(session).ensure_snapshot(snapshot)
            ensured.set()
            # Hold the transaction open, uncommitted, until cancelled.
            await release.wait()
            await session.commit()  # pragma: no cover - cancelled before commit.

    task = asyncio.create_task(ensure_then_stall())
    await ensured.wait()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert await _snapshot_row_count(session_factory, snapshot_id) == 0, (
        "a cancelled, uncommitted transaction must leave no snapshot row"
    )
    async with session_factory() as session:
        pins = (
            await session.execute(
                sa.select(sa.func.count(RunPricingPinRecord.workflow_run_id)).where(
                    RunPricingPinRecord.workflow_run_id == run_id
                )
            )
        ).scalar_one()
    assert pins == 0, "a cancelled transaction must leave no pin row"

    async with session_factory() as session:
        store = SqlAlchemyCostLedgerStore(session)
        await store.ensure_snapshot(snapshot)
        await store.pin_run_pricing(
            key,
            snapshot.pricing_snapshot_id,
            "2026-06-04T10:00:00Z",
        )
        await session.commit()

    assert await _snapshot_row_count(session_factory, snapshot_id) == 1, (
        "a retry after cancellation must persist the snapshot"
    )
