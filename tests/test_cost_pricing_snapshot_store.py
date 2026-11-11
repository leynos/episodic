"""Content addressing, round-trip, and tamper detection for snapshot storage."""

import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.cost import (
    BillingPeriodKey,
    PricingSnapshotError,
    PricingSnapshotId,
    PricingSnapshotIntegrityError,
    PricingSnapshotNotFoundError,
    RunPricingKey,
    SnapshotEnsureOutcome,
)
from episodic.cost.storage import (
    PricingSnapshotRecord,
    SqlAlchemyCostLedgerStore,
    SqlAlchemyPricingSnapshotStore,
)
from episodic.observability import RecordingTracer
from tests.fixtures.cost import v1_pricing_snapshot

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:  # pragma: no cover - runtime alias for evaluated test annotations.
    type SessionFactory = object


@pytest.mark.asyncio
async def test_ensure_is_content_addressed(session_factory: SessionFactory) -> None:
    """Equal content reuses one row even when built by separate calls."""
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)
        first = await snapshots.ensure(v1_pricing_snapshot())
        second = await snapshots.ensure(v1_pricing_snapshot())
        await session.commit()

    assert first.outcome is SnapshotEnsureOutcome.PERSISTED, (
        "the first ensure must insert the row"
    )
    assert second.outcome is SnapshotEnsureOutcome.REUSED, (
        "the second ensure must reuse the row"
    )
    assert first.pricing_snapshot_id == second.pricing_snapshot_id, (
        "equal content must resolve to one stored snapshot"
    )


@pytest.mark.asyncio
async def test_ensure_stores_exactly_one_row(session_factory: SessionFactory) -> None:
    """Repeated ensures never duplicate a content-addressed row."""
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)
        for _ in range(3):
            await snapshots.ensure(v1_pricing_snapshot())
        await session.commit()

    async with session_factory() as session:
        count = (
            await session.execute(sa.select(sa.func.count(PricingSnapshotRecord.id)))
        ).scalar_one()

    assert count == 1, "content addressing must keep one row per distinct content"


@pytest.mark.asyncio
async def test_get_round_trips_the_snapshot(session_factory: SessionFactory) -> None:
    """A stored snapshot reads back field-for-field identical."""
    original = v1_pricing_snapshot()
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(original)
        await session.commit()

    async with session_factory() as session:
        stored = await SqlAlchemyPricingSnapshotStore(session).get(
            ensured.pricing_snapshot_id
        )

    assert stored == original, "the stored row must rebuild the exact snapshot"
    assert stored.content_hash == original.content_hash, (
        "the round trip must preserve the content hash"
    )
    assert dict(stored.rates) == dict(original.rates), (
        "the round trip must preserve the exact rates"
    )


@pytest.mark.asyncio
async def test_get_rejects_a_tampered_row(session_factory: SessionFactory) -> None:
    """A row whose content no longer matches its hash is refused."""
    metric = "input_tokens"
    tampered_rate = {"amount_minor": 99, "per_units": 1, "unit": "token"}
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(
            v1_pricing_snapshot()
        )
        await session.commit()

    async with session_factory() as session:
        await session.execute(
            sa
            .update(PricingSnapshotRecord)
            .where(
                PricingSnapshotRecord.id == uuid.UUID(str(ensured.pricing_snapshot_id))
            )
            .values(rates={metric: tampered_rate})
        )
        await session.commit()

    tracer = RecordingTracer()
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session, tracer=tracer)

        with pytest.raises(PricingSnapshotIntegrityError, match="content hash"):
            await snapshots.get(ensured.pricing_snapshot_id)

    assert issubclass(PricingSnapshotIntegrityError, PricingSnapshotError), (
        "integrity failures must remain pricing snapshot failures"
    )
    assert (
        tracer.spans[0].attributes["failure_category"] == "pricing_snapshot.tampered"
    ), "the span must record a tamper failure"


@pytest.mark.asyncio
async def test_ensure_satisfies_a_run_pricing_pin(
    session_factory: SessionFactory,
) -> None:
    """A persisted snapshot identifier satisfies the pin foreign key."""
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(
            v1_pricing_snapshot()
        )
        await SqlAlchemyCostLedgerStore(session).pin_run_pricing(
            RunPricingKey(
                workflow_run_id="workflow-run-ensure",
                provider_name="openai",
                model="gpt-4o-mini",
                operation="chat_completions",
                billing_period_key=BillingPeriodKey("2026-06"),
            ),
            ensured.pricing_snapshot_id,
            "2026-06-04T10:00:00Z",
        )
        await session.commit()

    async with session_factory() as session:
        pinned = await SqlAlchemyCostLedgerStore(session).get_run_pricing_pin(
            RunPricingKey(
                workflow_run_id="workflow-run-ensure",
                provider_name="openai",
                model="gpt-4o-mini",
                operation="chat_completions",
                billing_period_key=BillingPeriodKey("2026-06"),
            )
        )

    assert pinned == ensured.pricing_snapshot_id, (
        "the pin must reference the content-addressed snapshot"
    )


@pytest.mark.asyncio
async def test_get_reports_an_unknown_identifier(
    session_factory: SessionFactory,
) -> None:
    """An unknown or malformed identifier raises the not-found error."""
    async with session_factory() as session:
        snapshots = SqlAlchemyPricingSnapshotStore(session)

        with pytest.raises(PricingSnapshotNotFoundError, match="No pricing snapshot"):
            await snapshots.get(
                PricingSnapshotId("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f96")
            )

        with pytest.raises(PricingSnapshotNotFoundError, match="No pricing snapshot"):
            await snapshots.get(PricingSnapshotId("not-a-uuid"))

    assert issubclass(PricingSnapshotNotFoundError, LookupError), (
        "callers that already catch LookupError must keep working"
    )
