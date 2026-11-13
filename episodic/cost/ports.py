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

Tests can use in-memory fakes; see ``tests/test_cost_ports_protocols.py``.
"""

import dataclasses as dc
import enum
import typing as typ

from episodic.cost.primitives import (
    BillingPeriodKey,
    CostAccountingError,
    CostLedgerEntryId,
    CurrencyCode,
    IdempotencyKey,
    MeteringCounterKey,
    PricingSnapshotId,
    validate_currency_code,
)
from episodic.cost.primitives import (
    PricingSourceKind as PricingSourceKind,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.cost.pricing_snapshot import PricingSnapshot, PricingSubject


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


class UsageSource(enum.StrEnum):
    """How usage metrics were obtained."""

    PROVIDER = "provider"
    ESTIMATED = "estimated"
    ROLLUP = "rollup"


class UnknownPricedMetricError(CostAccountingError):
    """Raised when usage includes a metric absent from the pricing snapshot."""


class OperationMismatchError(CostAccountingError):
    """Raised when a pricing snapshot is used for the wrong operation."""


def _validate_usage_metrics(usage: cabc.Mapping[str, int]) -> None:
    """Reject negative usage values before they reach pricing or storage."""
    negative_metrics = [metric for metric, value in usage.items() if value < 0]
    if negative_metrics:
        joined_metrics = ", ".join(sorted(negative_metrics))
        msg = f"usage metrics must be non-negative: {joined_metrics}"
        raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class PricedCall:
    """Computed cost for one provider call."""

    computed_cost_minor: int
    currency: CurrencyCode
    is_estimated: bool

    def __post_init__(self) -> None:
        """Validate cost invariants."""
        validate_currency_code(self.currency)
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
        validate_currency_code(self.currency)
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
        validate_currency_code(self.currency)
        if self.computed_cost_minor < 0:
            msg = "computed_cost_minor must be non-negative."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class RunPricingKey:
    """Composite key identifying one provider operation's pricing pin."""

    workflow_run_id: str
    provider_name: str
    model: str
    operation: str
    billing_period_key: BillingPeriodKey


@typ.runtime_checkable
class CostLedgerPort(typ.Protocol):
    """Port for append-only cost ledger persistence."""

    async def pin_run_pricing(
        self,
        key: RunPricingKey,
        pricing_snapshot_id: PricingSnapshotId,
        pinned_at: str,
    ) -> None:
        """Record a run-level pricing pin; silently reuse an existing pin."""
        raise NotImplementedError

    async def get_run_pricing_pin(self, key: RunPricingKey) -> PricingSnapshotId | None:
        """Return a pinned pricing snapshot identifier, if one exists."""
        raise NotImplementedError

    async def sum_provider_call_costs(self, workflow_run_id: str) -> int:
        """Return the total provider-call cost for one workflow run."""
        raise NotImplementedError

    async def record_call(self, entry: ProviderCallLedgerEntry) -> CostLedgerEntryId:
        """Record or return an idempotent provider-call ledger entry.

        Returns
        -------
        CostLedgerEntryId
            Identifier of the inserted or existing row; repeated calls
            with one idempotency key return the same identifier without
            creating duplicate rows.
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

    async def resolve(
        self,
        subject: PricingSubject,
        *,
        at: str | None = None,
    ) -> PricingSnapshot:
        """Resolve the pricing snapshot for a priced subject.

        Parameters
        ----------
        subject : PricingSubject
            Service kind, provider, model, and operation to price.
        at : str or None, optional
            ISO-8601 instant to resolve at. Defaults to the current time; a
            recorded call passes the instant it was captured so a later rate
            change cannot reprice it.

        Returns
        -------
        PricingSnapshot
            Immutable snapshot that prices the subject.

        Raises
        ------
        LookupError
            Raised when no applicable snapshot exists for the subject.
        NotImplementedError
            Raised by the protocol stub.

        Notes
        -----
        Implementations must return the snapshot applicable to the subject at
        ``at``. A snapshot is effective-dated, not billing-period-scoped, so
        the same card keeps pricing later periods until a newer one takes
        effect.
        """
        raise NotImplementedError


@typ.runtime_checkable
class MeteringPort(typ.Protocol):
    """Port for atomic usage-counter consumption."""

    async def consume(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # The parameter-rich signature is fixed by the explicit port or fixture contract.
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
