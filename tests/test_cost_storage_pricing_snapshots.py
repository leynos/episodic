"""Integration tests for the SQLAlchemy pricing-snapshot store."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.cost import (
    BillingPeriodKey,
    PricingSnapshotCollisionError,
    PricingSnapshotId,
    PricingSnapshotNotFoundError,
    RunPricingKey,
)
from episodic.cost.storage import (
    PricingSnapshotRecord,
    RunPricingPinRecord,
    SqlAlchemyCostLedgerStore,
    SqlAlchemyPricingSnapshotStore,
)
from tests.fixtures.cost import pricing_snapshot

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_ensure_persists_once_and_satisfies_pins(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensuring a snapshot inserts one row that run pricing pins can reference."""
    snapshot_id = "018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f90"
    snapshot = pricing_snapshot(snapshot_id)
    conflicting = dc.replace(
        snapshot,
        content_hash="ensure-hash-conflicting",
        rates_minor_per_metric={"input_tokens": 999, "output_tokens": 999},
    )
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)
        await snapshots.ensure(snapshot)
        await snapshots.ensure(snapshot)
        await snapshots.ensure(conflicting)
        await SqlAlchemyCostLedgerStore(session).pin_run_pricing(
            RunPricingKey(
                workflow_run_id="workflow-run-ensure",
                provider_name="openai",
                model="gpt-4o-mini",
                operation="chat_completions",
                billing_period_key=BillingPeriodKey("2026-06"),
            ),
            PricingSnapshotId(snapshot_id),
            "2026-06-04T10:00:00Z",
        )
        await session.commit()

    async with session_factory() as session:
        stored = (
            await session.execute(
                sa.select(sa.func.count(PricingSnapshotRecord.id)).where(
                    PricingSnapshotRecord.id == uuid.UUID(snapshot_id)
                )
            )
        ).scalar_one()
        stored_hash, stored_effective_from, stored_rates = (
            await session.execute(
                sa.select(
                    PricingSnapshotRecord.content_hash,
                    PricingSnapshotRecord.effective_from,
                    PricingSnapshotRecord.rates_minor_per_metric,
                ).where(PricingSnapshotRecord.id == uuid.UUID(snapshot_id))
            )
        ).one()
        pins = (
            await session.execute(
                sa.select(sa.func.count(RunPricingPinRecord.workflow_run_id))
            )
        ).scalar_one()

    assert stored == 1, "ensure must persist exactly one snapshot row"
    assert stored_hash == snapshot.content_hash, (
        "a later snapshot sharing the identifier must not overwrite the row"
    )
    assert stored_effective_from == dt.datetime(2026, 6, 1, tzinfo=dt.UTC), (
        "ensure must persist the snapshot's effective date"
    )
    assert stored_rates == dict(snapshot.rates_minor_per_metric), (
        "a conflicting snapshot must not replace the stored rate map"
    )
    assert pins == 1, "the pinned snapshot must satisfy the foreign key"


@pytest.mark.asyncio
async def test_ensure_rejects_content_hash_collisions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A duplicate content hash under a new identifier raises a domain error."""
    snapshot = pricing_snapshot("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f93")
    colliding = dc.replace(
        snapshot,
        pricing_snapshot_id=PricingSnapshotId("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f94"),
    )
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)
        await snapshots.ensure(snapshot)

        with pytest.raises(
            PricingSnapshotCollisionError,
            match="already stored under a different snapshot identifier",
        ):
            await snapshots.ensure(colliding)


@pytest.mark.asyncio
async def test_get_returns_the_persisted_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A stored snapshot is readable by identifier with its rates intact."""
    snapshot = pricing_snapshot("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f95")
    async with session_factory() as session:
        await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
        await session.commit()

    async with session_factory() as session:
        stored = await SqlAlchemyPricingSnapshotStore(session).get(
            snapshot.pricing_snapshot_id
        )

    assert stored.pricing_snapshot_id == snapshot.pricing_snapshot_id, (
        "the stored row must keep the snapshot identifier"
    )
    assert stored.rates_minor_per_metric == dict(snapshot.rates_minor_per_metric), (
        "the stored row must keep the exact rates"
    )
    assert stored.content_hash == snapshot.content_hash, (
        "the stored row must keep the content hash"
    )
    assert stored.effective_from == snapshot.effective_from, (
        "the stored row must keep the effective date"
    )
    assert dt.datetime.fromisoformat(stored.retrieved_at) == dt.datetime.fromisoformat(
        snapshot.retrieved_at
    ), "the stored row must keep the retrieval instant"


@pytest.mark.asyncio
async def test_get_reports_a_missing_snapshot_as_a_lookup_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An unknown identifier raises the repository's not-found error."""
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)

        with pytest.raises(PricingSnapshotNotFoundError, match="No pricing snapshot"):
            await snapshots.get(
                PricingSnapshotId("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f96")
            )

    assert issubclass(PricingSnapshotNotFoundError, LookupError), (
        "callers that already catch LookupError must keep working"
    )
