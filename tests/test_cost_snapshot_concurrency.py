"""Concurrency and cancellation coverage for snapshot persistence."""

import asyncio
import contextlib
import datetime as dt
import typing as typ

import pytest
import sqlalchemy as sa

from episodic.cost import (
    BillingPeriodKey,
    CurrencyCode,
    PricingSourceKind,
    RunPricingKey,
)
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    UsageUnit,
)
from episodic.cost.storage import (
    PricingSnapshotRecord,
    RunPricingPinRecord,
    SqlAlchemyCostLedgerStore,
    SqlAlchemyPricingSnapshotStore,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:  # pragma: no cover - runtime alias for evaluated test annotations.
    type SessionFactory = object


def _snapshot(source: str) -> PricingSnapshot:
    """Build a deterministic snapshot for concurrency scenarios."""
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={
            "input_tokens": MeteredRate.reduced(100, 1_000_000, UsageUnit.TOKEN),
            "output_tokens": MeteredRate.reduced(200, 1_000_000, UsageUnit.TOKEN),
        },
        source_metadata={"source": source},
        retrieved_at=dt.datetime(2026, 6, 4, 9, tzinfo=dt.UTC),
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
    content_hash: str,
) -> int:
    """Count persisted snapshot rows through a fresh session."""
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(sa.func.count(PricingSnapshotRecord.id)).where(
                    PricingSnapshotRecord.content_hash == content_hash
                )
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_concurrent_ensure_persists_exactly_one_snapshot(
    session_factory: SessionFactory,
) -> None:
    """Two sessions ensuring one snapshot leave exactly one immutable row."""
    snapshot = _snapshot("concurrency-test")
    start = asyncio.Event()

    async def ensure_once() -> None:
        """Ensure the snapshot and commit once the start event is set."""
        async with session_factory() as session:
            await start.wait()
            await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
            await session.commit()

    tasks = [asyncio.create_task(ensure_once()), asyncio.create_task(ensure_once())]
    start.set()
    await asyncio.gather(*tasks)

    assert await _snapshot_row_count(session_factory, snapshot.content_hash) == 1, (
        "concurrent ensures must persist exactly one snapshot row"
    )


@pytest.mark.asyncio
async def test_concurrent_ensure_and_pin_persist_one_snapshot_and_pin(
    session_factory: SessionFactory,
) -> None:
    """Two sessions racing ensure-then-pin leave one snapshot and one pin."""
    snapshot = _snapshot("concurrent-ensure-and-pin")
    run_id = f"run-{snapshot.content_hash[-8:]}"
    key = _pin_key(run_id)
    start = asyncio.Event()

    async def ensure_and_pin() -> None:
        """Ensure the snapshot, pin the run and commit once started."""
        async with session_factory() as session:
            await start.wait()
            ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
            await SqlAlchemyCostLedgerStore(session).pin_run_pricing(
                key,
                ensured.pricing_snapshot_id,
                "2026-06-04T10:00:00Z",
            )
            await session.commit()

    tasks = [
        asyncio.create_task(ensure_and_pin()),
        asyncio.create_task(ensure_and_pin()),
    ]
    start.set()
    await asyncio.gather(*tasks)

    assert await _snapshot_row_count(session_factory, snapshot.content_hash) == 1, (
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


@pytest.mark.asyncio
async def test_cancelled_transaction_leaves_no_partial_snapshot(
    session_factory: SessionFactory,
) -> None:
    """Cancellation before commit rolls back; a retry then succeeds."""
    snapshot = _snapshot("cancellation-test")
    run_id = f"run-{snapshot.content_hash[-8:]}"
    key = _pin_key(run_id)
    ensured = asyncio.Event()
    release = asyncio.Event()

    async def ensure_then_stall() -> None:
        """Ensure the snapshot and pin the run, then hold the transaction open."""
        async with session_factory() as session:
            stored = await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
            await SqlAlchemyCostLedgerStore(session).pin_run_pricing(
                key,
                stored.pricing_snapshot_id,
                "2026-06-04T10:00:00Z",
            )
            ensured.set()
            # Hold the transaction open, uncommitted, until cancelled.
            await release.wait()
            await session.commit()  # pragma: no cover - cancelled before commit.

    task = asyncio.create_task(ensure_then_stall())
    await ensured.wait()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert await _snapshot_row_count(session_factory, snapshot.content_hash) == 0, (
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
    assert pins == 0, "a cancelled transaction must roll back its uncommitted pin row"

    async with session_factory() as session:
        retried = await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
        await SqlAlchemyCostLedgerStore(session).pin_run_pricing(
            key,
            retried.pricing_snapshot_id,
            "2026-06-04T10:00:00Z",
        )
        await session.commit()

    assert await _snapshot_row_count(session_factory, snapshot.content_hash) == 1, (
        "a retry after cancellation must persist the snapshot"
    )
