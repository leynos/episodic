"""Tests for the cost recorder coordinator."""

import dataclasses as dc

import pytest

from episodic.cost.engine import PricingEngine
from episodic.cost.ports import (
    BillingPeriodKey,
    CostLedgerEntryId,
    CurrencyCode,
    IdempotencyKey,
    PricingModel,
    PricingSnapshot,
    PricingSnapshotId,
    PricingSourceKind,
    ProviderCallLedgerEntry,
    RunPricingKey,
    TaskRollupLedgerEntry,
    UsageSource,
)
from episodic.cost.recorder import CostRecorder, ProviderCallRecord


def _snapshot(
    pricing_snapshot_id: str,
    *,
    input_token_rate: int,
) -> PricingSnapshot:
    """Build a pricing snapshot for recorder tests.

    Parameters
    ----------
    pricing_snapshot_id
        Snapshot identifier to assign to the immutable test snapshot.
    input_token_rate
        Minor-unit rate to use for the ``input_tokens`` metric.

    Returns
    -------
    PricingSnapshot
        Immutable pricing snapshot with fixed test values.
    """
    return PricingSnapshot(
        pricing_snapshot_id=PricingSnapshotId(pricing_snapshot_id),
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        billing_period_key=BillingPeriodKey("2026-06"),
        rates_minor_per_metric={"input_tokens": input_token_rate},
        source_metadata={"source": "test"},
        content_hash=f"sha256:{pricing_snapshot_id}",
        retrieved_at="2026-06-04T00:00:00Z",
    )


@dc.dataclass(slots=True)
class _PinnedLedger:
    """Ledger fake that exposes one existing run pricing pin."""

    pinned_snapshot_id: PricingSnapshotId
    recorded_call: ProviderCallLedgerEntry | None = None

    async def pin_run_pricing(
        self,
        key: RunPricingKey,
        pricing_snapshot_id: PricingSnapshotId,
        pinned_at: str,
    ) -> None:
        """Accept a fake run-pricing pin."""
        _ = (key, pricing_snapshot_id, pinned_at)

    async def get_run_pricing_pin(self, key: RunPricingKey) -> PricingSnapshotId | None:
        """Return the fake pinned snapshot identifier."""
        _ = key
        return self.pinned_snapshot_id

    async def sum_provider_call_costs(self, workflow_run_id: str) -> int:
        """Return zero for tests that do not exercise roll-ups."""
        _ = workflow_run_id
        return 0

    async def record_call(self, entry: ProviderCallLedgerEntry) -> CostLedgerEntryId:
        """Capture the provider-call entry."""
        self.recorded_call = entry
        return CostLedgerEntryId("entry:provider-call")

    async def record_task_rollup(
        self,
        rollup: TaskRollupLedgerEntry,
    ) -> CostLedgerEntryId:
        """Accept a roll-up entry."""
        _ = rollup
        return CostLedgerEntryId("entry:rollup")


@dc.dataclass(frozen=True, slots=True)
class _DriftingCatalogue:
    """Catalogue fake with a latest snapshot and an older pinned snapshot."""

    pinned_snapshot: PricingSnapshot
    latest_snapshot: PricingSnapshot

    async def get_snapshot(
        self,
        pricing_snapshot_id: PricingSnapshotId,
    ) -> PricingSnapshot:
        """Return the exact pinned snapshot by identifier."""
        assert pricing_snapshot_id == self.pinned_snapshot.pricing_snapshot_id
        return self.pinned_snapshot

    async def resolve(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        provider_name: str,
        model: str,
        operation: str,
        billing_period_key: BillingPeriodKey,
    ) -> PricingSnapshot:
        """Return the latest resolvable snapshot."""
        _ = (provider_name, model, operation, billing_period_key)
        return self.latest_snapshot


@pytest.mark.asyncio
async def test_cost_recorder_prices_provider_call_with_pinned_snapshot() -> None:
    """Existing run pins keep historical rates even after catalogue drift."""
    pinned_snapshot = _snapshot("snapshot:old", input_token_rate=1_000_000)
    latest_snapshot = _snapshot("snapshot:new", input_token_rate=9_000_000)
    ledger = _PinnedLedger(pinned_snapshot_id=pinned_snapshot.pricing_snapshot_id)
    recorder = CostRecorder(
        ledger=ledger,
        pricing_catalogue=_DriftingCatalogue(
            pinned_snapshot=pinned_snapshot,
            latest_snapshot=latest_snapshot,
        ),
        pricing_engine=PricingEngine(),
    )

    await recorder.record_provider_call(
        ProviderCallRecord(
            idempotency_key=IdempotencyKey("run:abc:node:planner:call:1:attempt:0"),
            parent_cost_entry_id=None,
            provider_type="llm",
            provider_name="openai",
            model="gpt-4o-mini",
            workflow_node="planner",
            operation="chat_completions",
            usage={"input_tokens": 3},
            usage_source=UsageSource.PROVIDER,
            usage_complete=True,
            pricing_model=PricingModel.PAYG,
            retry_attempt=0,
            billing_period_key=BillingPeriodKey("2026-06"),
            workflow_run_id="run-abc",
            recorded_at="2026-06-04T00:00:00Z",
        ),
    )

    assert ledger.recorded_call is not None
    assert ledger.recorded_call.pricing_snapshot_id == PricingSnapshotId(
        "snapshot:old",
    ), "recorder must use the pinned snapshot identifier"
    assert ledger.recorded_call.computed_cost_minor == 3, (
        "cost must be computed from the pinned 1_000_000 rate, not drifted rates"
    )
