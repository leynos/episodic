"""Application coordinator for cost recording.

`CostRecorder` composes a pricing catalogue, the pure `PricingEngine`, and a
ledger port. Orchestration code submits a `ProviderCallRecord`; the recorder
resolves the pricing snapshot, computes a `PricedCall`, builds the ledger
entry, and delegates persistence to `CostLedgerPort`.

```python
recorder = CostRecorder(ledger, catalogue, PricingEngine())
entry_id = await recorder.record_provider_call(record)
```
"""

from __future__ import annotations

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
    PricingCataloguePort,
    PricingModel,
    PricingSnapshot,
    ProviderCallLedgerEntry,
    RunPricingKey,
    TaskRollupLedgerEntry,
    UsageSource,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.cost.engine import PricingEngine


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

    provider_name: str
    model: str
    operation: str


@dc.dataclass(frozen=True, slots=True)
class CostRecorder:
    """Coordinate pricing and ledger writes for orchestration code."""

    ledger: CostLedgerPort
    pricing_catalogue: PricingCataloguePort
    pricing_engine: PricingEngine

    async def _resolve_pricing_snapshot(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        provider_name: str,
        model: str,
        operation: str,
        billing_period_key: BillingPeriodKey,
    ) -> PricingSnapshot:
        """Resolve the snapshot that a run should use for this operation.

        Parameters
        ----------
        provider_name : str
            Provider identifier.
        model : str
            Provider model identifier.
        operation : str
            Provider operation to price.
        billing_period_key : BillingPeriodKey
            Billing period selected for the run.

        Returns
        -------
        PricingSnapshot
            Immutable snapshot that should be pinned for the run.

        Raises
        ------
        LookupError
            Propagated if the catalogue cannot resolve a snapshot.
        """
        return await self.pricing_catalogue.resolve(
            provider_name,
            model,
            operation,
            billing_period_key,
        )

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: tuple[CostProviderOperation, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Resolve and persist pricing pins for one workflow run."""
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
            snapshot = await self._resolve_pricing_snapshot(
                provider.provider_name,
                provider.model,
                provider.operation,
                billing_period_key,
            )
            await self.ledger.pin_run_pricing(
                key,
                snapshot.pricing_snapshot_id,
                pinned_at,
            )

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
            Propagated if pricing snapshot resolution fails.
        CostAccountingError
            Propagated if pricing validation fails.

        Notes
        -----
        This method resolves pricing through `pin_run_pricing`, delegates cost
        computation to `pricing_engine.price`, constructs a
        `ProviderCallLedgerEntry`, and persists it with `ledger.record_call`.
        """
        key = RunPricingKey(
            workflow_run_id=record.workflow_run_id,
            provider_name=record.provider_name,
            model=record.model,
            operation=record.operation,
            billing_period_key=record.billing_period_key,
        )
        pinned_snapshot_id = await self.ledger.get_run_pricing_pin(key)
        if pinned_snapshot_id is None:
            snapshot = await self._resolve_pricing_snapshot(
                record.provider_name,
                record.model,
                record.operation,
                record.billing_period_key,
            )
        else:
            snapshot = await self.pricing_catalogue.get_snapshot(pinned_snapshot_id)
        priced_call = self.pricing_engine.price(
            snapshot,
            PricingRequest(
                usage=record.usage,
                operation=record.operation,
                billing_period_key=record.billing_period_key,
                is_estimated=record.usage_source is UsageSource.ESTIMATED,
            ),
        )
        entry = ProviderCallLedgerEntry(
            idempotency_key=record.idempotency_key,
            parent_cost_entry_id=record.parent_cost_entry_id,
            scope=LedgerScope.PROVIDER_CALL,
            provider_type=record.provider_type,
            provider_name=record.provider_name,
            workflow_node=record.workflow_node,
            operation=record.operation,
            pricing_snapshot_id=snapshot.pricing_snapshot_id,
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
