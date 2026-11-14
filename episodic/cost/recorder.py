"""Application coordinator for cost recording.

`CostRecorder` composes a pricing catalogue, the pure `PricingEngine`, a
snapshot repository, and a ledger port. Orchestration code submits a
`ProviderCallRecord`; the recorder resolves the pricing snapshot, computes a
`PricedCall`, builds the ledger entry, and delegates persistence to
`CostLedgerPort`. Pinned runs are priced from the persisted snapshot, so edits
to the source rate card never reprice recorded history.

```python
recorder = CostRecorder(ledger, snapshots, catalogue, PricingEngine())
entry_id = await recorder.record_provider_call(record)
```
"""

import dataclasses as dc
import datetime as dt
import typing as typ

from episodic.cost.engine import PricingRequest
from episodic.cost.ports import (
    BillingPeriodKey,
    CostLedgerEntryId,
    CostLedgerPort,
    CurrencyCode,
    IdempotencyKey,
    LedgerScope,
    PricedCall,
    PricingCataloguePort,
    PricingModel,
    ProviderCallLedgerEntry,
    RunPricingKey,
    TaskRollupLedgerEntry,
    UsageSource,
)
from episodic.cost.pricing_snapshot import (
    PricedService,
    PricingSnapshot,
    PricingSubject,
    pricing_subject_of,
)
from episodic.cost.pricing_snapshot_ports import PricingSnapshotIntegrityError
from episodic.logging import get_logger, log_warning

_log = get_logger(__name__)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.cost.engine import PricingEngine
    from episodic.cost.pricing_snapshot_ports import PricingSnapshotRepository
    from episodic.cost.primitives import PricingSnapshotId


@dc.dataclass(frozen=True, slots=True)
class ProviderCallRecord:
    """Application request to record one provider call."""

    idempotency_key: IdempotencyKey
    parent_cost_entry_id: CostLedgerEntryId | None
    provider_type: str
    provider_name: str
    model: str
    workflow_node: str
    operation: str
    usage: cabc.Mapping[str, int]
    usage_source: UsageSource
    usage_complete: bool
    pricing_model: PricingModel
    retry_attempt: int
    billing_period_key: BillingPeriodKey
    workflow_run_id: str
    recorded_at: str


@dc.dataclass(frozen=True, slots=True)
class CostProviderOperation:
    """Provider operation whose pricing should be pinned for a run."""

    service_kind: PricedService
    provider_name: str
    model: str
    operation: str

    @property
    def subject(self) -> PricingSubject:
        """The priced subject this operation pins."""
        return pricing_subject_of(self)


@typ.runtime_checkable
class CostRecorderPort(typ.Protocol):
    """Application port for recording the costs of one workflow run."""

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: tuple[CostProviderOperation, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Pin pricing snapshots before recording provider calls."""
        raise NotImplementedError

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> CostLedgerEntryId:
        """Record one priced provider call and return its ledger entry id."""
        raise NotImplementedError

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> CostLedgerEntryId:
        """Write the final run roll-up and return its ledger entry id."""
        raise NotImplementedError


@dc.dataclass(frozen=True, slots=True)
class CostRecorder:
    """Coordinate pricing and ledger writes for orchestration code."""

    ledger: CostLedgerPort
    snapshots: PricingSnapshotRepository
    pricing_catalogue: PricingCataloguePort
    pricing_engine: PricingEngine

    async def _resolve_pricing_snapshot(
        self,
        subject: PricingSubject,
        *,
        at: str | None = None,
    ) -> PricingSnapshot:
        """Resolve the snapshot that a run should use for this subject.

        Parameters
        ----------
        subject : PricingSubject
            Service kind, provider, model, and operation to price.
        at : str or None, optional
            ISO-8601 instant the call was captured at. Defaults to now, which
            is correct when pinning a run before its calls are made.

        Returns
        -------
        PricingSnapshot
            Immutable snapshot that should be pinned for the run.
        """
        return await self.pricing_catalogue.resolve(subject, at=at)

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: tuple[CostProviderOperation, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Resolve and persist pricing pins for one workflow run.

        Raises
        ------
        LookupError
            If the catalogue cannot resolve a pricing snapshot.
        CostAccountingError
            If pricing or ledger validation fails.
        """  # ruff: ignore[docstring-extraneous-exception]  # Collaborating ports propagate these domain exceptions.
        pinned_at = dt.datetime.now(dt.UTC).isoformat()
        for provider in providers:
            key = RunPricingKey(
                workflow_run_id=workflow_run_id,
                provider_name=provider.provider_name,
                model=provider.model,
                operation=provider.operation,
                billing_period_key=billing_period_key,
            )
            existing_pin = await self.ledger.get_run_pricing_pin(key)
            if existing_pin is not None:
                continue
            snapshot = await self._resolve_pricing_snapshot(provider.subject)
            ensured = await self.snapshots.ensure(snapshot)
            await self.ledger.pin_run_pricing(
                key,
                ensured.pricing_snapshot_id,
                pinned_at,
            )

    @staticmethod
    def _build_provider_call_entry(
        record: ProviderCallRecord,
        pricing_snapshot_id: PricingSnapshotId,
        priced_call: PricedCall,
    ) -> ProviderCallLedgerEntry:
        """Construct a provider-call ledger entry from priced call data."""
        return ProviderCallLedgerEntry(
            idempotency_key=record.idempotency_key,
            parent_cost_entry_id=record.parent_cost_entry_id,
            scope=LedgerScope.PROVIDER_CALL,
            provider_type=record.provider_type,
            provider_name=record.provider_name,
            workflow_node=record.workflow_node,
            operation=record.operation,
            pricing_snapshot_id=pricing_snapshot_id,
            usage=record.usage,
            usage_source=record.usage_source,
            usage_complete=record.usage_complete,
            computed_cost_minor=priced_call.computed_cost_minor,
            currency=priced_call.currency,
            pricing_model=record.pricing_model,
            retry_attempt=record.retry_attempt,
            billing_period_key=record.billing_period_key,
            workflow_run_id=record.workflow_run_id,
            recorded_at=record.recorded_at,
        )

    @staticmethod
    def _record_subject(record: ProviderCallRecord) -> PricingSubject:
        """Return the priced subject a provider-call record describes."""
        try:
            service_kind = PricedService(record.provider_type)
        except ValueError:
            msg = (
                f"provider_type {record.provider_type!r} does not name a "
                "priced service kind."
            )
            raise ValueError(msg) from None
        return PricingSubject(
            service_kind=service_kind,
            provider_name=record.provider_name,
            model=record.model,
            operation=record.operation,
        )

    async def _resolve_snapshot_for_record(
        self, record: ProviderCallRecord
    ) -> tuple[PricingSnapshot, PricingSnapshotId]:
        """Resolve the stored snapshot and its identifier for a provider call."""
        key = RunPricingKey(
            workflow_run_id=record.workflow_run_id,
            provider_name=record.provider_name,
            model=record.model,
            operation=record.operation,
            billing_period_key=record.billing_period_key,
        )
        pinned_snapshot_id = await self.ledger.get_run_pricing_pin(key)
        if pinned_snapshot_id is not None:
            pinned = await self.snapshots.get(pinned_snapshot_id)
            subject = self._record_subject(record)
            if pinned.subject != subject:
                # The pin key omits the service kind, so two service kinds that
                # share every other field would collide. Refuse rather than
                # price this call with another service's rates.
                msg = (
                    f"pinned pricing snapshot {pinned_snapshot_id} prices "
                    f"{pinned.subject!r}, not {subject!r}."
                )
                # The refusal is the only signal that a run pinned the wrong
                # snapshot kind; without it the failure looks like any other
                # integrity error in the logs.
                log_warning(
                    _log,
                    "pricing_snapshot_pin_refused snapshot=%s pinned=%r requested=%r",
                    pinned_snapshot_id,
                    pinned.subject,
                    subject,
                )
                raise PricingSnapshotIntegrityError(msg)
            return pinned, pinned_snapshot_id
        # Resolve at the instant the call was captured, not at wall-clock now:
        # a card that became effective in between must not reprice this call.
        snapshot = await self._resolve_pricing_snapshot(
            self._record_subject(record),
            at=record.recorded_at,
        )
        # Unpinned calls must persist the snapshot before the ledger row
        # references it; pinned calls skip this because the pin's foreign key
        # already guarantees the stored row exists.
        ensured = await self.snapshots.ensure(snapshot)
        return snapshot, ensured.pricing_snapshot_id

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> CostLedgerEntryId:
        """Price and record a provider-call ledger entry.

        Parameters
        ----------
        record : ProviderCallRecord
            Provider-call details collected by orchestration.

        Returns
        -------
        CostLedgerEntryId
            Identifier returned by the ledger port.

        Raises
        ------
        LookupError
            If the catalogue cannot resolve a pricing snapshot.
        CostAccountingError
            If pricing or ledger validation fails.
        """  # ruff: ignore[docstring-extraneous-exception]  # Collaborating ports propagate these domain exceptions.
        snapshot, pricing_snapshot_id = await self._resolve_snapshot_for_record(record)
        priced_call = self.pricing_engine.price(
            snapshot,
            PricingRequest(
                usage=record.usage,
                operation=record.operation,
                is_estimated=record.usage_source is UsageSource.ESTIMATED,
            ),
        )
        entry = self._build_provider_call_entry(
            record,
            pricing_snapshot_id,
            priced_call,
        )
        return await self.ledger.record_call(entry)

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> CostLedgerEntryId:
        """Record the final run roll-up from persisted provider-call costs."""
        total_cost_minor = await self.ledger.sum_provider_call_costs(workflow_run_id)
        rollup = TaskRollupLedgerEntry(
            idempotency_key=IdempotencyKey(f"run:{workflow_run_id}:rollup"),
            workflow_run_id=workflow_run_id,
            workflow_node=workflow_node,
            computed_cost_minor=total_cost_minor,
            currency=CurrencyCode("USD"),
            billing_period_key=BillingPeriodKey(
                dt.datetime.now(dt.UTC).strftime("%Y-%m")
            ),
            recorded_at=dt.datetime.now(dt.UTC).isoformat(),
        )
        return await self.record_task_rollup(rollup)

    async def record_task_rollup(
        self,
        rollup: TaskRollupLedgerEntry,
    ) -> CostLedgerEntryId:
        """Record a final task or run-level roll-up.

        Parameters
        ----------
        rollup : TaskRollupLedgerEntry
            Roll-up entry computed at task or run completion.

        Returns
        -------
        CostLedgerEntryId
            Identifier returned by the ledger port.

        Notes
        -----
        The recorder delegates idempotency and persistence to
        `ledger.record_task_rollup`.
        """
        return await self.ledger.record_task_rollup(rollup)
