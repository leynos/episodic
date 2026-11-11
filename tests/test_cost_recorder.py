"""Tests for the cost recorder coordinator."""

import dataclasses as dc
import datetime as dt
import uuid

import pytest

from episodic.cost import CurrencyCode, PricingSourceKind
from episodic.cost.engine import PricingEngine
from episodic.cost.ports import (
    BillingPeriodKey,
    CostLedgerEntryId,
    IdempotencyKey,
    PricingModel,
    PricingSnapshotId,
    ProviderCallLedgerEntry,
    RunPricingKey,
    TaskRollupLedgerEntry,
    UsageSource,
)
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    PricingSubject,
    UsageUnit,
)
from episodic.cost.pricing_snapshot_ports import (
    EnsuredPricingSnapshot,
    PricingSnapshotNotFoundError,
    SnapshotEnsureOutcome,
)
from episodic.cost.recorder import (
    CostProviderOperation,
    CostRecorder,
    ProviderCallRecord,
)


def _snapshot(*, input_token_rate: int) -> PricingSnapshot:
    """Build an immutable pricing snapshot for recorder tests.

    Parameters
    ----------
    input_token_rate
        Minor units charged per one million ``input_tokens``.

    Returns
    -------
    PricingSnapshot
        Immutable pricing snapshot with fixed test values.
    """
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={
            "input_tokens": MeteredRate.reduced(
                input_token_rate,
                1_000_000,
                UsageUnit.TOKEN,
            ),
        },
        source_metadata={"source": "test"},
        retrieved_at=dt.datetime(2026, 6, 4, tzinfo=dt.UTC),
    )


def _surrogate_id(snapshot: PricingSnapshot) -> PricingSnapshotId:
    """Derive a stable surrogate identifier from a snapshot's content hash."""
    return PricingSnapshotId(str(uuid.uuid5(uuid.NAMESPACE_URL, snapshot.content_hash)))


@dc.dataclass(slots=True)
class _RecordingSnapshots:
    """Snapshot repository fake recording calls while holding one snapshot."""

    stored_snapshot: PricingSnapshot
    calls: list[tuple[str, PricingSnapshotId]] = dc.field(default_factory=list)
    ensured_snapshots: list[PricingSnapshot] = dc.field(default_factory=list)

    async def ensure(self, snapshot: PricingSnapshot) -> EnsuredPricingSnapshot:
        """Capture snapshots the recorder persists, mirroring idempotency."""
        pricing_snapshot_id = _surrogate_id(snapshot)
        self.calls.append(("ensure", pricing_snapshot_id))
        if snapshot.content_hash in {
            stored.content_hash for stored in self.ensured_snapshots
        }:
            outcome = SnapshotEnsureOutcome.REUSED
        else:
            self.ensured_snapshots.append(snapshot)
            outcome = SnapshotEnsureOutcome.PERSISTED
        return EnsuredPricingSnapshot(
            pricing_snapshot_id=pricing_snapshot_id,
            outcome=outcome,
        )

    async def get(self, pricing_snapshot_id: PricingSnapshotId) -> PricingSnapshot:
        """Return the stored snapshot or raise the port's not-found error."""
        self.calls.append(("get", pricing_snapshot_id))
        if pricing_snapshot_id != _surrogate_id(self.stored_snapshot):
            msg = f"No pricing snapshot found for id {pricing_snapshot_id}."
            raise PricingSnapshotNotFoundError(msg)
        return self.stored_snapshot


@dc.dataclass(slots=True)
class _PinnedLedger:
    """Ledger fake that exposes one existing run pricing pin."""

    pinned_snapshot_id: PricingSnapshotId | None
    recorded_call: ProviderCallLedgerEntry | None = None
    calls: list[tuple[str, PricingSnapshotId]] = dc.field(default_factory=list)

    async def pin_run_pricing(
        self,
        key: RunPricingKey,
        pricing_snapshot_id: PricingSnapshotId,
        pinned_at: str,
    ) -> None:
        """Accept a fake run-pricing pin, recording the call order."""
        _ = (key, pinned_at)
        self.calls.append(("pin", pricing_snapshot_id))

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
    """Catalogue fake that always resolves the latest authored snapshot."""

    latest_snapshot: PricingSnapshot

    async def resolve(self, subject: PricingSubject) -> PricingSnapshot:
        """Return the latest resolvable snapshot."""
        _ = subject
        return self.latest_snapshot


def _provider_call_record() -> ProviderCallRecord:
    """Build a provider-call record with fixed test values."""
    return ProviderCallRecord(
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
    )


@pytest.mark.asyncio
async def test_cost_recorder_prices_provider_call_with_pinned_snapshot() -> None:
    """Existing run pins keep historical rates even after catalogue drift."""
    pinned_snapshot = _snapshot(input_token_rate=1_000_000)
    latest_snapshot = _snapshot(input_token_rate=9_000_000)
    ledger = _PinnedLedger(pinned_snapshot_id=_surrogate_id(pinned_snapshot))
    snapshots = _RecordingSnapshots(stored_snapshot=pinned_snapshot)
    recorder = CostRecorder(
        ledger=ledger,
        snapshots=snapshots,
        pricing_catalogue=_DriftingCatalogue(latest_snapshot=latest_snapshot),
        pricing_engine=PricingEngine(),
    )

    await recorder.record_provider_call(_provider_call_record())

    assert ledger.recorded_call is not None, "Expected value to be present"
    assert ledger.recorded_call.pricing_snapshot_id == _surrogate_id(pinned_snapshot), (
        "recorder must use the pinned snapshot identifier"
    )
    assert ledger.recorded_call.computed_cost_minor == 3, (
        "cost must be computed from the pinned 1_000_000 rate, not drifted rates"
    )
    assert snapshots.calls == [("get", _surrogate_id(pinned_snapshot))], (
        "pinned calls must read the stored snapshot rather than the catalogue"
    )


@pytest.mark.asyncio
async def test_cost_recorder_persists_snapshot_for_unpinned_provider_call() -> None:
    """Unpinned calls persist the resolved snapshot before the ledger row."""
    latest_snapshot = _snapshot(input_token_rate=1_000_000)
    ledger = _PinnedLedger(pinned_snapshot_id=None)
    snapshots = _RecordingSnapshots(stored_snapshot=latest_snapshot)
    recorder = CostRecorder(
        ledger=ledger,
        snapshots=snapshots,
        pricing_catalogue=_DriftingCatalogue(latest_snapshot=latest_snapshot),
        pricing_engine=PricingEngine(),
    )

    await recorder.record_provider_call(_provider_call_record())

    assert snapshots.ensured_snapshots == [latest_snapshot], (
        "unpinned calls must persist the resolved snapshot before recording"
    )
    assert ledger.recorded_call is not None, "Expected value to be present"
    assert ledger.recorded_call.pricing_snapshot_id == _surrogate_id(latest_snapshot), (
        "the ledger row must reference the persisted snapshot"
    )


@pytest.mark.asyncio
async def test_cost_recorder_persists_snapshot_before_pinning() -> None:
    """The real pin method ensures the snapshot before writing the pin."""
    snapshot = _snapshot(input_token_rate=1_000_000)
    calls: list[tuple[str, PricingSnapshotId]] = []
    ledger = _PinnedLedger(pinned_snapshot_id=None, calls=calls)
    snapshots = _RecordingSnapshots(stored_snapshot=snapshot, calls=calls)
    recorder = CostRecorder(
        ledger=ledger,
        snapshots=snapshots,
        pricing_catalogue=_DriftingCatalogue(latest_snapshot=snapshot),
        pricing_engine=PricingEngine(),
    )

    await recorder.pin_run_pricing(
        "run-pin-order",
        (
            CostProviderOperation(
                service_kind=PricedService.LLM,
                provider_name="openai",
                model="gpt-4o-mini",
                operation="chat_completions",
            ),
        ),
        BillingPeriodKey("2026-06"),
    )

    assert calls == [
        ("ensure", _surrogate_id(snapshot)),
        ("pin", _surrogate_id(snapshot)),
    ], f"the snapshot must be persisted before it is pinned; got {calls!r}"
