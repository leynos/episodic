"""Cost accounting domain ports and pricing helpers.

The `episodic.cost` package exposes the public cost-accounting contracts used
by orchestration code. It contains immutable value objects for pricing
snapshots and ledger entries, Protocol-based ports for ledger, catalogue, and
metering adapters, and `PricingEngine` for deterministic integer minor-unit
cost calculation.

Typical application code wires concrete adapters at the composition root,
then coordinates pricing through `CostRecorder`:

```python
recorder = CostRecorder(ledger, snapshots, catalogue, PricingEngine())
entry_id = await recorder.record_provider_call(record)
```

The public API is the set of names exported through `__all__`.
"""

from episodic.cost.engine import PricingEngine
from episodic.cost.ports import (
    BillingPeriodKey,
    CostLedgerEntryId,
    CostLedgerPort,
    CurrencyCode,
    IdempotencyKey,
    LedgerScope,
    MeteringCounterKey,
    MeteringPort,
    PricedCall,
    PricingCataloguePort,
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
    SourceDocument,
    UsageUnit,
)
from episodic.cost.pricing_snapshot_ports import (
    EnsuredPricingSnapshot,
    PricingSnapshotError,
    PricingSnapshotIntegrityError,
    PricingSnapshotNotFoundError,
    PricingSnapshotRepository,
    SnapshotEnsureOutcome,
)
from episodic.cost.primitives import PricingSourceKind
from episodic.cost.recorder import CostRecorderPort

__all__ = [
    "BillingPeriodKey",
    "CostLedgerEntryId",
    "CostLedgerPort",
    "CostRecorderPort",
    "CurrencyCode",
    "EnsuredPricingSnapshot",
    "IdempotencyKey",
    "LedgerScope",
    "MeteredRate",
    "MeteringCounterKey",
    "MeteringPort",
    "PricedCall",
    "PricedService",
    "PricingCataloguePort",
    "PricingEngine",
    "PricingModel",
    "PricingSnapshot",
    "PricingSnapshotError",
    "PricingSnapshotId",
    "PricingSnapshotIntegrityError",
    "PricingSnapshotNotFoundError",
    "PricingSnapshotRepository",
    "PricingSourceKind",
    "PricingSubject",
    "ProviderCallLedgerEntry",
    "RunPricingKey",
    "SnapshotEnsureOutcome",
    "SourceDocument",
    "TaskRollupLedgerEntry",
    "UsageSource",
    "UsageUnit",
]
