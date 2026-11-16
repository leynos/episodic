"""SQLAlchemy-backed cost-accounting storage adapters.

This package exposes records and adapters for cost ledger entries, metering
counters, pricing snapshots, and run pricing pins. The stores depend on a
SQLAlchemy ``AsyncSession`` owned by the caller:

```python
async with session_factory() as session:
    store = SqlAlchemyCostLedgerStore(session)
    await store.record_call(entry)
    snapshots = SqlAlchemyPricingSnapshotStore(session)
    await snapshots.ensure(snapshot)
```
"""

from .adapters import SqlAlchemyCostLedgerStore
from .metering import SqlAlchemyMeteringCounterStore
from .models import (
    CostLedgerEntryRecord,
    MeteringCounterEventRecord,
    MeteringCounterRecord,
    PricingSnapshotRecord,
    RunPricingPinRecord,
)
from .pricing_snapshot_store import SqlAlchemyPricingSnapshotStore
from .pricing_snapshot_telemetry import InstrumentedPricingSnapshotRepository

__all__ = [
    "CostLedgerEntryRecord",
    "InstrumentedPricingSnapshotRepository",
    "MeteringCounterEventRecord",
    "MeteringCounterRecord",
    "PricingSnapshotRecord",
    "RunPricingPinRecord",
    "SqlAlchemyCostLedgerStore",
    "SqlAlchemyMeteringCounterStore",
    "SqlAlchemyPricingSnapshotStore",
]
