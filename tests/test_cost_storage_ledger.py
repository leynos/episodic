"""Integration tests for the SQLAlchemy cost ledger adapter."""

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.cost import (
    BillingPeriodKey,
    CurrencyCode,
    IdempotencyKey,
    LedgerScope,
    PricingModel,
    PricingSnapshotId,
    ProviderCallLedgerEntry,
    TaskRollupLedgerEntry,
    UsageSource,
)
from episodic.cost.storage import (
    CostLedgerEntryRecord,
    PricingSnapshotRecord,
    SqlAlchemyCostLedgerStore,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _provider_call_entry(
    key: str = "run-1:planner:0:call-1",
) -> ProviderCallLedgerEntry:
    """Build a representative provider-call ledger entry."""
    return ProviderCallLedgerEntry(
        idempotency_key=IdempotencyKey(key),
        parent_cost_entry_id=None,
        scope=LedgerScope.PROVIDER_CALL,
        provider_type="llm",
        provider_name="openai",
        workflow_node="planner",
        operation="chat_completions",
        pricing_snapshot_id=PricingSnapshotId("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f8f"),
        usage={"input_tokens": 1000, "output_tokens": 250},
        usage_source=UsageSource.PROVIDER,
        usage_complete=True,
        computed_cost_minor=42,
        currency=CurrencyCode("USD"),
        pricing_model=PricingModel.PAYG,
        retry_attempt=0,
        billing_period_key=BillingPeriodKey("2026-06"),
        workflow_run_id="workflow-run-1",
        recorded_at="2026-06-04T10:00:00Z",
    )


def _pricing_snapshot_record() -> PricingSnapshotRecord:
    """Build the pricing snapshot referenced by provider-call fixtures."""
    return PricingSnapshotRecord(
        id=uuid.UUID("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f8f"),
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind="provider_rate_card",
        currency="USD",
        billing_period_key="2026-06",
        rates_minor_per_metric={"input_tokens": 100, "output_tokens": 200},
        source_metadata={"source_url": "https://example.test/pricing"},
        content_hash="fixture-hash",
        retrieved_at=dt.datetime(2026, 6, 4, 9, 0, tzinfo=dt.UTC),
        effective_from=dt.datetime(2026, 6, 1, 0, 0, tzinfo=dt.UTC),
    )


@pytest.mark.asyncio
async def test_record_call_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repeated provider-call inserts converge on one ledger row."""
    async with session_factory() as session:
        session.add(_pricing_snapshot_record())
        await session.flush()
        store = SqlAlchemyCostLedgerStore(session)
        first_id = await store.record_call(_provider_call_entry())
        second_id = await store.record_call(_provider_call_entry())
        await session.commit()

    async with session_factory() as session:
        row_count = (
            await session.execute(sa.select(sa.func.count(CostLedgerEntryRecord.id)))
        ).scalar_one()

    assert first_id == second_id, "expected identical IDs for idempotent record_call"
    assert row_count == 1, (
        f"expected single ledger row after idempotent calls, got {row_count}"
    )


@pytest.mark.asyncio
async def test_record_task_rollup_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repeated roll-up inserts converge on one ledger row."""
    rollup = TaskRollupLedgerEntry(
        idempotency_key=IdempotencyKey("run:workflow-run-1:rollup"),
        workflow_run_id="workflow-run-1",
        workflow_node=None,
        computed_cost_minor=42,
        currency=CurrencyCode("USD"),
        billing_period_key=BillingPeriodKey("2026-06"),
        recorded_at="2026-06-04T10:01:00Z",
    )
    async with session_factory() as session:
        store = SqlAlchemyCostLedgerStore(session)
        first_id = await store.record_task_rollup(rollup)
        second_id = await store.record_task_rollup(rollup)
        await session.commit()

    async with session_factory() as session:
        records = (
            (await session.execute(sa.select(CostLedgerEntryRecord))).scalars().all()
        )

    assert first_id == second_id, "expected idempotent record IDs to match"
    assert len(records) == 1, (
        "expected a single CostLedgerEntryRecord after idempotent inserts"
    )
    assert records[0].scope == LedgerScope.TASK, "expected record scope to be TASK"


@pytest.mark.asyncio
async def test_rollup_query_sums_provider_call_costs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Provider-call rows remain queryable by workflow run and scope."""
    async with session_factory() as session:
        session.add(_pricing_snapshot_record())
        await session.flush()
        store = SqlAlchemyCostLedgerStore(session)
        await store.record_call(_provider_call_entry("run-1:planner:0:call-1"))
        await store.record_call(_provider_call_entry("run-1:show-notes:0:call-1"))
        await session.commit()

    async with session_factory() as session:
        total = (
            await session.execute(
                sa.select(sa.func.sum(CostLedgerEntryRecord.computed_cost_minor)).where(
                    CostLedgerEntryRecord.workflow_run_id == "workflow-run-1",
                    CostLedgerEntryRecord.scope == LedgerScope.PROVIDER_CALL,
                )
            )
        ).scalar_one()

    assert total == 84, f"expected sum of provider call costs to be 84 but got {total}"


def test_recorded_at_fixture_is_timezone_aware() -> None:
    """Keep date parsing expectations visible for storage tests."""
    parsed = dt.datetime.fromisoformat("2026-06-04T10:00:00+00:00")

    assert parsed.tzinfo is not None, "expected parsed datetime to be timezone-aware"
