"""Shared cost-accounting domain fixtures, builders, and port fakes."""

import dataclasses as dc
import datetime as dt
import uuid

from episodic.cost import CurrencyCode, PricingSourceKind
from episodic.cost.ports import (
    CostLedgerEntryId,
    ProviderCallLedgerEntry,
    RunPricingKey,
    TaskRollupLedgerEntry,
)
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    UsageUnit,
)
from episodic.cost.pricing_snapshot_ports import (
    EnsuredPricingSnapshot,
    PricingSnapshotNotFoundError,
    SnapshotEnsureOutcome,
)
from episodic.cost.primitives import PricingSnapshotId

V1_RETRIEVED_AT = dt.datetime(2026, 6, 4, 9, tzinfo=dt.UTC)


def v1_pricing_snapshot() -> PricingSnapshot:
    """Build a representative schema-version-1 pricing snapshot.

    Returns
    -------
    PricingSnapshot
        Snapshot pricing ``gpt-4o-mini`` chat completions in USD.

    Examples
    --------
    >>> v1_pricing_snapshot().provider_name
    'openai'
    """
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={
            "input_tokens": MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN),
            "output_tokens": MeteredRate.reduced(60, 1_000_000, UsageUnit.TOKEN),
        },
        source_metadata={"source_url": "https://example.test/pricing"},
        retrieved_at=V1_RETRIEVED_AT,
        effective_from=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
    )


def surrogate_snapshot_id(snapshot: PricingSnapshot) -> PricingSnapshotId:
    """Derive a stable surrogate identifier from a snapshot's content hash.

    The real repository assigns identifiers, so a fake that must predict one
    derives it from the content hash: the same snapshot always maps to the
    same identifier, and a different snapshot maps to a different one.

    Parameters
    ----------
    snapshot : PricingSnapshot
        Snapshot whose identifier is wanted.

    Returns
    -------
    PricingSnapshotId
        Identifier derived from the snapshot's content hash.

    Examples
    --------
    >>> surrogate_snapshot_id(v1_pricing_snapshot()) == surrogate_snapshot_id(
    ...     v1_pricing_snapshot()
    ... )
    True
    """
    return PricingSnapshotId(str(uuid.uuid5(uuid.NAMESPACE_URL, snapshot.content_hash)))


@dc.dataclass(slots=True)
class RecordingSnapshots:
    """Snapshot repository fake that records calls and holds one snapshot.

    ``ensure`` mirrors the real repository's idempotency: a snapshot whose
    content hash is already held is reported as reused. ``get`` returns the
    held snapshot only for its derived identifier, so a test can prove which
    snapshot the recorder read.

    Examples
    --------
    >>> snapshots = RecordingSnapshots(snapshot=v1_pricing_snapshot())
    >>> snapshots.snapshot.model
    'gpt-4o-mini'
    """

    snapshot: PricingSnapshot
    calls: list[tuple[str, PricingSnapshotId]] = dc.field(default_factory=list)
    ensured_snapshots: list[PricingSnapshot] = dc.field(default_factory=list)

    async def ensure(self, snapshot: PricingSnapshot) -> EnsuredPricingSnapshot:
        """Record the persist request, mirroring content-hash idempotency."""
        pricing_snapshot_id = surrogate_snapshot_id(snapshot)
        self.calls.append(("ensure", pricing_snapshot_id))
        held = {stored.content_hash for stored in self.ensured_snapshots}
        if snapshot.content_hash in held:
            outcome = SnapshotEnsureOutcome.REUSED
        else:
            self.ensured_snapshots.append(snapshot)
            outcome = SnapshotEnsureOutcome.PERSISTED
        return EnsuredPricingSnapshot(
            pricing_snapshot_id=pricing_snapshot_id,
            outcome=outcome,
        )

    async def get(self, pricing_snapshot_id: PricingSnapshotId) -> PricingSnapshot:
        """Return the held snapshot, or raise the port's not-found error."""
        self.calls.append(("get", pricing_snapshot_id))
        if pricing_snapshot_id != surrogate_snapshot_id(self.snapshot):
            msg = f"No pricing snapshot found for id {pricing_snapshot_id}."
            raise PricingSnapshotNotFoundError(msg)
        return self.snapshot


@dc.dataclass(slots=True)
class RecordingLedger:
    """Cost ledger fake exposing one optional run pin and capturing writes.

    Examples
    --------
    >>> ledger = RecordingLedger()
    >>> ledger.pinned_snapshot_id is None
    True
    """

    pinned_snapshot_id: PricingSnapshotId | None = None
    recorded_call: ProviderCallLedgerEntry | None = None
    calls: list[tuple[str, PricingSnapshotId]] = dc.field(default_factory=list)

    async def pin_run_pricing(
        self,
        key: RunPricingKey,
        pricing_snapshot_id: PricingSnapshotId,
        pinned_at: str,
    ) -> None:
        """Accept a run-pricing pin, recording the call order."""
        _ = (key, pinned_at)
        self.calls.append(("pin", pricing_snapshot_id))

    async def get_run_pricing_pin(self, key: RunPricingKey) -> PricingSnapshotId | None:
        """Return the configured pinned snapshot identifier."""
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
