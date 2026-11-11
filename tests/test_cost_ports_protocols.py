"""Port contract tests for cost accounting protocols."""

import dataclasses as dc
import datetime as dt
import inspect
import uuid

import pytest

from episodic.cost import CurrencyCode, PricingSourceKind
from episodic.cost.engine import PricingEngine, PricingRequest
from episodic.cost.ports import (
    BillingPeriodKey,
    CostLedgerEntryId,
    CostLedgerPort,
    IdempotencyKey,
    MeteringCounterKey,
    MeteringPort,
    PricedCall,
    PricingCataloguePort,
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
    PricingSnapshotRepository,
    SnapshotEnsureOutcome,
)
from episodic.cost.recorder import CostRecorderPort
from episodic.llm.ports import LLMResponse, LLMUsage, ProviderCallUsage
from tests.generation_run_launcher_support import RecordingCostRecorder

_DEFAULT_SUBJECT = PricingSubject(
    service_kind=PricedService.LLM,
    provider_name="vidai",
    model="mock-gpt",
    operation="chat_completions",
)


def _make_snapshot(subject: PricingSubject = _DEFAULT_SUBJECT) -> PricingSnapshot:
    """Build a deterministic pricing snapshot for protocol tests."""
    return PricingSnapshot(
        service_kind=subject.service_kind,
        provider_name=subject.provider_name,
        model=subject.model,
        operation=subject.operation,
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={
            "input_tokens": MeteredRate.reduced(1, 1, UsageUnit.TOKEN),
        },
        source_metadata={"source": "test"},
        retrieved_at=dt.datetime(2026, 6, 4, tzinfo=dt.UTC),
    )


class _InMemoryCostLedger:
    """Fake cost ledger for protocol conformance tests."""

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


class _InMemoryPricingSnapshots:
    """Fake snapshot repository keyed by content hash, like the real store."""

    def __init__(self) -> None:
        """Start with no stored snapshots."""
        self._stored: dict[PricingSnapshotId, PricingSnapshot] = {}
        self._by_content_hash: dict[str, PricingSnapshotId] = {}

    async def ensure(self, snapshot: PricingSnapshot) -> EnsuredPricingSnapshot:
        """Store the snapshot once and report whether this call inserted it."""
        existing = self._by_content_hash.get(snapshot.content_hash)
        if existing is not None:
            return EnsuredPricingSnapshot(
                pricing_snapshot_id=existing,
                outcome=SnapshotEnsureOutcome.REUSED,
            )
        # The real store assigns a UUIDv7 surrogate on first insert and reuses
        # it for the same content hash thereafter.
        pricing_snapshot_id = PricingSnapshotId(str(uuid.uuid7()))
        self._by_content_hash[snapshot.content_hash] = pricing_snapshot_id
        self._stored[pricing_snapshot_id] = snapshot
        return EnsuredPricingSnapshot(
            pricing_snapshot_id=pricing_snapshot_id,
            outcome=SnapshotEnsureOutcome.PERSISTED,
        )

    async def get(self, pricing_snapshot_id: PricingSnapshotId) -> PricingSnapshot:
        """Return the stored snapshot or raise the not-found port error."""
        try:
            return self._stored[pricing_snapshot_id]
        except KeyError as exc:
            msg = f"No pricing snapshot found for id {pricing_snapshot_id}."
            raise PricingSnapshotNotFoundError(msg) from exc


class _StaticPricingCatalogue:
    """Fake pricing catalogue that returns a deterministic snapshot."""

    async def resolve(self, subject: PricingSubject) -> PricingSnapshot:
        """Return a deterministic snapshot for protocol conformance tests."""
        return _make_snapshot(subject)


class _InMemoryMetering:
    """Fake metering port that echoes the consumed delta."""

    async def consume(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # The parameter-rich signature is fixed by the explicit port or fixture contract.
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
    snapshots = _InMemoryPricingSnapshots()
    catalogue = _StaticPricingCatalogue()
    metering = _InMemoryMetering()

    assert isinstance(ledger, CostLedgerPort), (
        "Expected value to have the required type"
    )
    assert inspect.iscoroutinefunction(ledger.pin_run_pricing), (
        "Expected condition to hold"
    )
    assert inspect.iscoroutinefunction(ledger.get_run_pricing_pin), (
        "Expected condition to hold"
    )
    assert inspect.iscoroutinefunction(ledger.sum_provider_call_costs), (
        "Expected condition to hold"
    )
    assert inspect.iscoroutinefunction(ledger.record_call), "Expected condition to hold"
    assert inspect.iscoroutinefunction(ledger.record_task_rollup), (
        "Expected condition to hold"
    )
    assert isinstance(snapshots, PricingSnapshotRepository), (
        "Expected value to have the required type"
    )
    assert inspect.iscoroutinefunction(snapshots.ensure), "Expected condition to hold"
    assert inspect.iscoroutinefunction(snapshots.get), "Expected condition to hold"
    assert isinstance(catalogue, PricingCataloguePort), (
        "Expected value to have the required type"
    )
    assert inspect.iscoroutinefunction(catalogue.resolve), "Expected condition to hold"
    assert isinstance(metering, MeteringPort), (
        "Expected value to have the required type"
    )
    assert inspect.iscoroutinefunction(metering.consume), "Expected condition to hold"


def test_recording_cost_recorder_satisfies_public_port() -> None:
    """The generation-run recorder fake matches the public cost contract."""
    recorder = RecordingCostRecorder()

    assert isinstance(recorder, CostRecorderPort), (
        "Expected value to have the required type"
    )
    assert inspect.iscoroutinefunction(recorder.pin_run_pricing), (
        "Expected condition to hold"
    )
    assert inspect.iscoroutinefunction(recorder.record_provider_call), (
        "Expected condition to hold"
    )
    assert inspect.iscoroutinefunction(recorder.finalize_run), (
        "Expected condition to hold"
    )


def test_pricing_engine_returns_priced_call() -> None:
    """The pricing engine has the deterministic domain pricing surface."""
    snapshot = _make_snapshot()

    priced_call = PricingEngine().price(
        snapshot,
        PricingRequest(
            usage={"input_tokens": 3},
            operation="chat_completions",
        ),
    )

    assert isinstance(priced_call, PricedCall), (
        "Expected value to have the required type"
    )
    assert priced_call.computed_cost_minor == 3, "Expected values to match"


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

    assert response.provider_call_usage == provider_usage, "Expected values to match"
    assert legacy_response.provider_call_usage is None, "Expected value to be absent"


def test_pricing_snapshot_rejects_naive_effective_from() -> None:
    """A naive effective date must fail value-object validation."""
    aware = _make_snapshot()

    with pytest.raises(ValueError, match="effective_from must be timezone-aware"):
        dc.replace(
            aware,
            effective_from=dt.datetime(2026, 6, 1),  # ruff: ignore[call-datetime-without-tzinfo] - naive on purpose.
        )


def test_pricing_snapshot_rejects_non_datetime_effective_from() -> None:
    """A non-datetime effective date must fail with a TypeError."""
    aware = _make_snapshot()

    with pytest.raises(TypeError, match="effective_from must be a datetime"):
        dc.replace(
            aware,
            effective_from="2026-06-01T00:00:00Z",  # type: ignore[arg-type]  # invalid on purpose.
        )
