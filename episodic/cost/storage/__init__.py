"""SQLAlchemy-backed cost-accounting storage adapters.

This package exposes records and adapters for cost ledger entries, metering
counters, pricing snapshots, and run pricing pins. The stores depend on a
SQLAlchemy ``AsyncSession`` owned by the caller:

```python
async with session_factory() as session:
    store = SqlAlchemyCostLedgerStore(session)
    await store.record_call(entry)
```
"""

from .adapters import SqlAlchemyCostLedgerStore, SqlAlchemyMeteringCounterStore
from .models import (
    CostLedgerEntryRecord,
    MeteringCounterEventRecord,
    MeteringCounterRecord,
    PricingSnapshotRecord,
    RunPricingPinRecord,
)

__all__ = [
    "CostLedgerEntryRecord",
    "MeteringCounterEventRecord",
    "MeteringCounterRecord",
    "PricingSnapshotRecord",
    "RunPricingPinRecord",
    "SqlAlchemyCostLedgerStore",
    "SqlAlchemyMeteringCounterStore",
]
