"""Port contract tests for cost accounting protocols."""

import inspect

from episodic.cost.engine import PricingEngine, PricingRequest
from episodic.cost.ports import (
    BillingPeriodKey,
    CostLedgerEntryId,
    CostLedgerPort,
    CurrencyCode,
    IdempotencyKey,
    MeteringCounterKey,
    MeteringPort,
    PricedCall,
    PricingCataloguePort,
    PricingSnapshot,
    PricingSnapshotId,
    PricingSourceKind,
    ProviderCallLedgerEntry,
    RunPricingKey,
    TaskRollupLedgerEntry,
    UsageSource,
)
from episodic.llm.ports import LLMResponse, LLMUsage, ProviderCallUsage

_DEFAULT_BILLING_PERIOD = BillingPeriodKey("2026-06")
_DEFAULT_SNAPSHOT_KEY = RunPricingKey(
    workflow_run_id="run:test",
    provider_name="vidai",
    model="mock-gpt",
    operation="chat_completions",
    billing_period_key=_DEFAULT_BILLING_PERIOD,
)


def _make_snapshot(
    pricing_snapshot_id: PricingSnapshotId,
    *,
    key: RunPricingKey = _DEFAULT_SNAPSHOT_KEY,
) -> PricingSnapshot:
    """Build a deterministic pricing snapshot for protocol tests."""
    return PricingSnapshot(
        pricing_snapshot_id=pricing_snapshot_id,
        provider_name=key.provider_name,
        model=key.model,
        operation=key.operation,
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        billing_period_key=key.billing_period_key,
        rates_minor_per_metric={"input_tokens": 1_000_000},
        source_metadata={"source": "test"},
        content_hash="sha256:test",
        retrieved_at="2026-06-04T00:00:00Z",
    )


class _InMemoryCostLedger:
    async def pin_run_pricing(
        self,
        key: RunPricingKey,
        pricing_snapshot_id: PricingSnapshotId,
        pinned_at: str,
    ) -> None:
        """Accept a fake run-pricing pin."""
        _ = (key, pricing_snapshot_id, pinned_at)

    async def get_run_pricing_pin(self, key: RunPricingKey) -> PricingSnapshotId | None:
        """Return no fake pricing pin by default."""
        _ = key
        return None

    async def sum_provider_call_costs(self, workflow_run_id: str) -> int:
        """Return a deterministic fake run total."""
        _ = workflow_run_id
        return 0

    async def record_call(self, entry: ProviderCallLedgerEntry) -> CostLedgerEntryId:
        """Record a provider call and return a stable fake identifier."""
        return CostLedgerEntryId(f"call:{entry.idempotency_key}")

    async def record_task_rollup(
        self,
        rollup: TaskRollupLedgerEntry,
    ) -> CostLedgerEntryId:
        """Record a roll-up and return a stable fake identifier."""
        return CostLedgerEntryId(f"rollup:{rollup.idempotency_key}")


class _StaticPricingCatalogue:
    async def get_snapshot(
        self,
        pricing_snapshot_id: PricingSnapshotId,
    ) -> PricingSnapshot:
        """Return a deterministic snapshot for protocol conformance tests."""
        return _make_snapshot(pricing_snapshot_id)

    async def resolve(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        provider_name: str,
        model: str,
        operation: str,
        billing_period_key: BillingPeriodKey,
    ) -> PricingSnapshot:
        """Return a deterministic snapshot for protocol conformance tests."""
        return _make_snapshot(
            PricingSnapshotId("snapshot:test"),
            key=RunPricingKey(
                workflow_run_id="run:test",
                provider_name=provider_name,
                model=model,
                operation=operation,
                billing_period_key=billing_period_key,
            ),
        )


class _InMemoryMetering:
    async def consume(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        counter_key: MeteringCounterKey,
        billing_period_key: BillingPeriodKey,
        delta: int,
        idempotency_key: IdempotencyKey,
    ) -> int:
        """Consume a fake counter delta."""
        _ = (counter_key, billing_period_key, idempotency_key)
        return delta


def test_cost_protocol_fakes_satisfy_public_ports() -> None:
    """Concrete cost collaborators expose the published protocol surfaces."""
    ledger = _InMemoryCostLedger()
    catalogue = _StaticPricingCatalogue()
    metering = _InMemoryMetering()

    assert isinstance(ledger, CostLedgerPort)
    assert inspect.iscoroutinefunction(ledger.pin_run_pricing)
    assert inspect.iscoroutinefunction(ledger.get_run_pricing_pin)
    assert inspect.iscoroutinefunction(ledger.sum_provider_call_costs)
    assert inspect.iscoroutinefunction(ledger.record_call)
    assert inspect.iscoroutinefunction(ledger.record_task_rollup)
    assert isinstance(catalogue, PricingCataloguePort)
    assert inspect.iscoroutinefunction(catalogue.get_snapshot)
    assert inspect.iscoroutinefunction(catalogue.resolve)
    assert isinstance(metering, MeteringPort)
    assert inspect.iscoroutinefunction(metering.consume)


def test_pricing_engine_returns_priced_call() -> None:
    """The pricing engine has the deterministic domain pricing surface."""
    snapshot = _make_snapshot(PricingSnapshotId("snapshot:test"))

    priced_call = PricingEngine().price(
        snapshot,
        PricingRequest(
            usage={"input_tokens": 3},
            operation="chat_completions",
            billing_period_key=BillingPeriodKey("2026-06"),
        ),
    )

    assert isinstance(priced_call, PricedCall)
    assert priced_call.computed_cost_minor == 3


def test_llm_response_accepts_optional_provider_call_usage() -> None:
    """Provider-specific usage travels beside the stable aggregate usage."""
    provider_usage = ProviderCallUsage(
        usage_metrics={"input_tokens": 10, "cached_input_tokens": 4},
        usage_source=UsageSource.PROVIDER,
        usage_complete=True,
        provider_response_id="resp-123",
        finish_reason="stop",
        started_at="2026-06-04T00:00:00Z",
        latency_ms=42,
    )

    response = LLMResponse(
        text="done",
        model="mock-gpt",
        provider_response_id="resp-123",
        finish_reason="stop",
        usage=LLMUsage(input_tokens=10, output_tokens=2, total_tokens=12),
        provider_call_usage=provider_usage,
    )
    legacy_response = LLMResponse(
        text="done",
        model="mock-gpt",
        provider_response_id="resp-124",
        finish_reason="stop",
        usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2),
    )

    assert response.provider_call_usage == provider_usage
    assert legacy_response.provider_call_usage is None
