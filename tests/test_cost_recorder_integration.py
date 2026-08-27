"""Integration tests for the cost recorder against SQL persistence."""

import dataclasses as dc
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.cost import (
    BillingPeriodKey,
    PricingSnapshot,
    PricingSnapshotId,
)
from episodic.cost.storage import (
    PricingSnapshotRecord,
    RunPricingPinRecord,
    SqlAlchemyCostLedgerStore,
)
from tests.test_cost_storage_ledger import _pricing_snapshot

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(frozen=True, slots=True)
class _SingleSnapshotCatalogue:
    """Catalogue fake resolving one fixed snapshot."""

    snapshot: PricingSnapshot

    async def get_snapshot(
        self,
        pricing_snapshot_id: PricingSnapshotId,
    ) -> PricingSnapshot:
        """Return the fixture snapshot for its identifier."""
        assert pricing_snapshot_id == self.snapshot.pricing_snapshot_id, (
            "Expected the fixture snapshot identifier"
        )
        return self.snapshot

    async def resolve(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # The parameter-rich signature is fixed by the explicit port or fixture contract.
        self,
        provider_name: str,
        model: str,
        operation: str,
        billing_period_key: BillingPeriodKey,
    ) -> PricingSnapshot:
        """Return the fixture snapshot for any lookup."""
        _ = (provider_name, model, operation, billing_period_key)
        return self.snapshot


@pytest.mark.asyncio
async def test_cost_recorder_pins_on_a_fresh_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The real recorder persists the snapshot before the foreign-key pin."""
    from episodic.cost.engine import PricingEngine
    from episodic.cost.recorder import CostProviderOperation, CostRecorder

    snapshot = _pricing_snapshot("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f97")
    async with session_factory() as session:
        recorder = CostRecorder(
            ledger=SqlAlchemyCostLedgerStore(session),
            pricing_catalogue=_SingleSnapshotCatalogue(snapshot),
            pricing_engine=PricingEngine(),
        )
        await recorder.pin_run_pricing(
            "workflow-run-fresh-pin",
            (
                CostProviderOperation(
                    provider_name="openai",
                    model="gpt-4o-mini",
                    operation="chat_completions",
                ),
            ),
            BillingPeriodKey("2026-06"),
        )
        await session.commit()

    async with session_factory() as session:
        stored = (
            await session.execute(
                sa.select(sa.func.count(PricingSnapshotRecord.id)).where(
                    PricingSnapshotRecord.id
                    == uuid.UUID("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f97")
                )
            )
        ).scalar_one()
        pinned = (
            await session.execute(
                sa.select(RunPricingPinRecord.pricing_snapshot_id).where(
                    RunPricingPinRecord.workflow_run_id == "workflow-run-fresh-pin"
                )
            )
        ).scalar_one()

    assert stored == 1, "pinning on a fresh database must persist the snapshot"
    assert str(pinned) == "018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f97", (
        "the pin must reference the persisted snapshot"
    )
