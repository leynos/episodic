"""Cost accounting ports and value objects.

`episodic.cost.ports` defines the domain-side contracts for pricing and cost
ledger work. A port is a Protocol owned by the domain or application boundary;
outbound adapters implement these Protocols without leaking SQLAlchemy,
provider SDKs, or network clients inward.

The core Protocols are `CostLedgerPort` for append-only ledger persistence,
`PricingCataloguePort` for resolving immutable pricing snapshots, and
`MeteringPort` for atomic usage-counter consumption. The value objects in this
module are frozen dataclasses or `NewType` aliases that carry immutable
snapshot, priced-call, and ledger-entry data.

Tests can use small in-memory fakes that structurally satisfy the Protocols:

```python
class FakeLedger:
    async def record_call(self, entry: ProviderCallLedgerEntry) -> CostLedgerEntryId:
        return CostLedgerEntryId(str(entry.idempotency_key))
```
"""

from __future__ import annotations

import dataclasses as dc
import enum
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_ISO_CURRENCY_CODE_LENGTH = 3


class LedgerScope(enum.StrEnum):
    """Supported cost ledger scopes."""

    TASK = "task"
    PROVIDER_CALL = "provider_call"
    INTERNAL_ESTIMATE = "internal_estimate"
    FIXED_ALLOCATION = "fixed_allocation"


class PricingModel(enum.StrEnum):
    """Supported pricing model families."""

    PAYG = "payg"
    ROLLUP = "rollup"
    QUOTA_OVERAGE = "quota_overage"
    SUBSCRIPTION_ALLOCATED = "subscription_allocated"


class PricingSourceKind(enum.StrEnum):
    """Source document type for a pricing snapshot."""

    PROVIDER_RATE_CARD = "provider_rate_card"
    SLA4OAI_PLAN = "sla4oai_plan"


class UsageSource(enum.StrEnum):
    """How usage metrics were obtained."""

    PROVIDER = "provider"
    ESTIMATED = "estimated"
    ROLLUP = "rollup"


PricingSnapshotId = typ.NewType("PricingSnapshotId", str)
CostLedgerEntryId = typ.NewType("CostLedgerEntryId", str)
IdempotencyKey = typ.NewType("IdempotencyKey", str)
CurrencyCode = typ.NewType("CurrencyCode", str)
BillingPeriodKey = typ.NewType("BillingPeriodKey", str)
MeteringCounterKey = typ.NewType("MeteringCounterKey", str)


class CostAccountingError(Exception):
    """Base exception for cost accounting failures."""


class UnknownPricedMetricError(CostAccountingError):
    """Raised when usage includes a metric absent from the pricing snapshot."""


class OperationMismatchError(CostAccountingError):
    """Raised when a pricing snapshot is used for the wrong operation."""


class BillingPeriodMismatchError(CostAccountingError):
    """Raised when a pricing snapshot is used for the wrong billing period."""


def _validate_currency_code(currency: CurrencyCode) -> None:
    """Validate an ISO 4217-style currency code."""
    currency_value = str(currency)
    if len(currency_value) != _ISO_CURRENCY_CODE_LENGTH or not currency_value.isalpha():
        msg = "currency must be a three-letter ISO 4217 code."
        raise ValueError(msg)
    if currency_value != currency_value.upper():
        msg = "currency must use uppercase ISO 4217 letters."
        raise ValueError(msg)


def _validate_usage_metrics(usage: cabc.Mapping[str, int]) -> None:
    """Reject negative usage values before they reach pricing or storage."""
    negative_metrics = [metric for metric, value in usage.items() if value < 0]
    if negative_metrics:
        joined_metrics = ", ".join(sorted(negative_metrics))
        msg = f"usage metrics must be non-negative: {joined_metrics}"
        raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class PricingSnapshot:
    """Immutable pricing input used by the deterministic pricing engine."""

    pricing_snapshot_id: PricingSnapshotId
    provider_name: str
    model: str
    operation: str
    source_kind: PricingSourceKind
    currency: CurrencyCode
    billing_period_key: BillingPeriodKey
    rates_minor_per_metric: cabc.Mapping[str, int]
    source_metadata: cabc.Mapping[str, str]
    content_hash: str
    retrieved_at: str

    def __post_init__(self) -> None:
        """Validate value-object invariants."""
        _validate_currency_code(self.currency)
        _validate_usage_metrics(self.rates_minor_per_metric)


@dc.dataclass(frozen=True, slots=True)
class PricedCall:
    """Computed cost for one provider call."""

    computed_cost_minor: int
    currency: CurrencyCode
    is_estimated: bool

    def __post_init__(self) -> None:
        """Validate cost invariants."""
        _validate_currency_code(self.currency)
        if self.computed_cost_minor < 0:
            msg = "computed_cost_minor must be non-negative."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class ProviderCallLedgerEntry:
    """Ledger row for one billable provider interaction."""

    idempotency_key: IdempotencyKey
    parent_cost_entry_id: CostLedgerEntryId | None
    scope: LedgerScope
    provider_type: str
    provider_name: str
    workflow_node: str
    operation: str
    pricing_snapshot_id: PricingSnapshotId
    usage: cabc.Mapping[str, int]
    usage_source: UsageSource
    usage_complete: bool
    computed_cost_minor: int
    currency: CurrencyCode
    pricing_model: PricingModel
    retry_attempt: int
    billing_period_key: BillingPeriodKey
    workflow_run_id: str
    recorded_at: str

    def __post_init__(self) -> None:
        """Validate ledger entry invariants."""
        _validate_currency_code(self.currency)
        _validate_usage_metrics(self.usage)
        if self.computed_cost_minor < 0:
            msg = "computed_cost_minor must be non-negative."
            raise ValueError(msg)
        if self.retry_attempt < 0:
            msg = "retry_attempt must be non-negative."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class TaskRollupLedgerEntry:
    """Ledger row for a task or run-level cost roll-up."""

    idempotency_key: IdempotencyKey
    workflow_run_id: str
    workflow_node: str | None
    computed_cost_minor: int
    currency: CurrencyCode
    billing_period_key: BillingPeriodKey
    recorded_at: str

    def __post_init__(self) -> None:
        """Validate roll-up entry invariants."""
        _validate_currency_code(self.currency)
        if self.computed_cost_minor < 0:
            msg = "computed_cost_minor must be non-negative."
            raise ValueError(msg)


@typ.runtime_checkable
class CostLedgerPort(typ.Protocol):
    """Port for append-only cost ledger persistence."""

    async def record_call(self, entry: ProviderCallLedgerEntry) -> CostLedgerEntryId:
        """Record or return an idempotent provider-call ledger entry.

        Parameters
        ----------
        entry : ProviderCallLedgerEntry
            Provider-call ledger entry to persist.

        Returns
        -------
        CostLedgerEntryId
            Identifier of the inserted or existing ledger row.

        Notes
        -----
        Repeated calls with the same idempotency key must return the same
        `CostLedgerEntryId` without creating duplicate rows.
        """
        raise NotImplementedError

    async def record_task_rollup(
        self,
        rollup: TaskRollupLedgerEntry,
    ) -> CostLedgerEntryId:
        """Record or return an idempotent task roll-up ledger entry.

        Parameters
        ----------
        rollup : TaskRollupLedgerEntry
            Task or run-level roll-up to persist.

        Returns
        -------
        CostLedgerEntryId
            Identifier of the inserted or existing roll-up row.

        Notes
        -----
        Repeated calls with the same idempotency key must return the same
        `CostLedgerEntryId` without creating duplicate rows.
        """
        raise NotImplementedError


@typ.runtime_checkable
class PricingCataloguePort(typ.Protocol):
    """Port for resolving immutable pricing snapshots."""

    async def resolve(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        provider_name: str,
        model: str,
        operation: str,
        billing_period_key: BillingPeriodKey,
    ) -> PricingSnapshot:
        """Resolve the pricing snapshot for a provider operation.

        Parameters
        ----------
        provider_name : str
            Provider identifier, for example `openai`.
        model : str
            Provider model identifier.
        operation : str
            Provider operation, for example `chat_completions`.
        billing_period_key : BillingPeriodKey
            Billing period used to select the immutable rate card.

        Returns
        -------
        PricingSnapshot
            Immutable snapshot that prices the provider operation.

        Raises
        ------
        NotImplementedError
            Raised by the protocol stub.

        Notes
        -----
        Implementations must return the snapshot pinned for the provider,
        model, operation, and billing period tuple.
        """
        raise NotImplementedError


@typ.runtime_checkable
class MeteringPort(typ.Protocol):
    """Port for atomic usage-counter consumption."""

    async def consume(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        counter_key: MeteringCounterKey,
        billing_period_key: BillingPeriodKey,
        delta: int,
        idempotency_key: IdempotencyKey,
    ) -> int:
        """Consume a metric delta and return the period's consumed total.

        Parameters
        ----------
        counter_key : MeteringCounterKey
            Metering counter identifier.
        billing_period_key : BillingPeriodKey
            Billing period for the counter update.
        delta : int
            Usage increment to consume.
        idempotency_key : IdempotencyKey
            Key that prevents duplicate consumption on retry.

        Returns
        -------
        int
            Cumulative consumed total after applying `delta`.

        Notes
        -----
        Implementations must apply the update atomically and treat repeated
        `idempotency_key` values as at-most-once consumption.
        """
        raise NotImplementedError
