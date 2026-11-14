"""Tests for the cost recorder coordinator."""

import dataclasses as dc
import datetime as dt

import pytest

from episodic.cost import (
    CurrencyCode,
    PricingSnapshotIntegrityError,
    PricingSourceKind,
)
from episodic.cost import recorder as recorder_module
from episodic.cost.engine import PricingEngine
from episodic.cost.ports import (
    BillingPeriodKey,
    IdempotencyKey,
    PricingModel,
    PricingSnapshotId,
    UsageSource,
)
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    PricingSubject,
    UsageUnit,
)
from episodic.cost.recorder import (
    CostProviderOperation,
    CostRecorder,
    ProviderCallRecord,
)
from tests.fixtures.cost import (
    RecordingLedger,
    RecordingSnapshots,
    surrogate_snapshot_id,
)


def _snapshot(*, input_token_rate: int) -> PricingSnapshot:
    """Build an immutable pricing snapshot for recorder tests.

    Parameters
    ----------
    input_token_rate
        Minor units charged per one million ``input_tokens``.

    Returns
    -------
    PricingSnapshot
        Immutable pricing snapshot with fixed test values.
    """
    return PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
        currency=CurrencyCode("USD"),
        rates={
            "input_tokens": MeteredRate.reduced(
                input_token_rate,
                1_000_000,
                UsageUnit.TOKEN,
            ),
        },
        source_metadata={"source": "test"},
        retrieved_at=dt.datetime(2026, 6, 4, tzinfo=dt.UTC),
    )


@dc.dataclass(frozen=True, slots=True)
class _DriftingCatalogue:
    """Catalogue fake that always resolves the latest authored snapshot."""

    latest_snapshot: PricingSnapshot
    resolved_at: list[str | None] = dc.field(default_factory=list)

    async def resolve(
        self,
        subject: PricingSubject,
        *,
        at: str | None = None,
    ) -> PricingSnapshot:
        """Return the latest resolvable snapshot, recording the cutoff."""
        del subject
        self.resolved_at.append(at)
        return self.latest_snapshot


def _provider_call_record() -> ProviderCallRecord:
    """Build a provider-call record with fixed test values."""
    return ProviderCallRecord(
        idempotency_key=IdempotencyKey("run:abc:node:planner:call:1:attempt:0"),
        parent_cost_entry_id=None,
        provider_type="llm",
        provider_name="openai",
        model="gpt-4o-mini",
        workflow_node="planner",
        operation="chat_completions",
        usage={"input_tokens": 3},
        usage_source=UsageSource.PROVIDER,
        usage_complete=True,
        pricing_model=PricingModel.PAYG,
        retry_attempt=0,
        billing_period_key=BillingPeriodKey("2026-06"),
        workflow_run_id="run-abc",
        recorded_at="2026-06-04T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_cost_recorder_prices_provider_call_with_pinned_snapshot() -> None:
    """Existing run pins keep historical rates even after catalogue drift."""
    pinned_snapshot = _snapshot(input_token_rate=1_000_000)
    latest_snapshot = _snapshot(input_token_rate=9_000_000)
    ledger = RecordingLedger(pinned_snapshot_id=surrogate_snapshot_id(pinned_snapshot))
    snapshots = RecordingSnapshots(snapshot=pinned_snapshot)
    recorder = CostRecorder(
        ledger=ledger,
        snapshots=snapshots,
        pricing_catalogue=_DriftingCatalogue(latest_snapshot=latest_snapshot),
        pricing_engine=PricingEngine(),
    )

    await recorder.record_provider_call(_provider_call_record())

    assert ledger.recorded_call is not None, "Expected value to be present"
    assert ledger.recorded_call.pricing_snapshot_id == surrogate_snapshot_id(
        pinned_snapshot
    ), "recorder must use the pinned snapshot identifier"
    assert ledger.recorded_call.computed_cost_minor == 3, (
        "cost must be computed from the pinned 1_000_000 rate, not drifted rates"
    )
    assert snapshots.calls == [("get", surrogate_snapshot_id(pinned_snapshot))], (
        "pinned calls must read the stored snapshot rather than the catalogue"
    )


def _capture_pin_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, tuple[object, ...]]]:
    """Record the warnings the recorder emits through the logging port."""
    emitted: list[tuple[str, tuple[object, ...]]] = []

    def _record(_logger: object, template: str, *args: object) -> None:
        """Keep the template and its arguments for later assertion."""
        emitted.append((template, args))

    monkeypatch.setattr(recorder_module, "log_warning", _record)
    return emitted


@pytest.mark.asyncio
async def test_cost_recorder_rejects_a_pin_for_another_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pin that prices a different subject must not price this call."""
    pinned_snapshot = _snapshot(input_token_rate=1_000_000)
    other_subject = dc.replace(pinned_snapshot, operation="synthesize")
    ledger = RecordingLedger(pinned_snapshot_id=surrogate_snapshot_id(other_subject))
    recorder = CostRecorder(
        ledger=ledger,
        snapshots=RecordingSnapshots(snapshot=other_subject),
        pricing_catalogue=_DriftingCatalogue(latest_snapshot=pinned_snapshot),
        pricing_engine=PricingEngine(),
    )
    refusals = _capture_pin_refusals(monkeypatch)

    with pytest.raises(PricingSnapshotIntegrityError, match="prices"):
        await recorder.record_provider_call(_provider_call_record())

    assert ledger.recorded_call is None, "a mismatched pin must not record a cost"
    assert len(refusals) == 1, f"a refused pin must be reported once: {refusals!r}"
    template, args = refusals[0]
    assert "pin_refused" in template, (
        f"the diagnostic must be identifiable by name, got {template!r}"
    )
    assert args[0] == surrogate_snapshot_id(other_subject), (
        "the diagnostic must name the refused snapshot"
    )
    assert args[1] == other_subject.subject, (
        "the diagnostic must name the subject the pin prices"
    )


@pytest.mark.asyncio
async def test_cost_recorder_persists_snapshot_for_unpinned_provider_call() -> None:
    """Unpinned calls persist the resolved snapshot before the ledger row."""
    latest_snapshot = _snapshot(input_token_rate=1_000_000)
    ledger = RecordingLedger(pinned_snapshot_id=None)
    snapshots = RecordingSnapshots(snapshot=latest_snapshot)
    recorder = CostRecorder(
        ledger=ledger,
        snapshots=snapshots,
        pricing_catalogue=_DriftingCatalogue(latest_snapshot=latest_snapshot),
        pricing_engine=PricingEngine(),
    )

    await recorder.record_provider_call(_provider_call_record())

    assert snapshots.ensured_snapshots == [latest_snapshot], (
        "unpinned calls must persist the resolved snapshot before recording"
    )
    assert ledger.recorded_call is not None, "Expected value to be present"
    assert ledger.recorded_call.pricing_snapshot_id == surrogate_snapshot_id(
        latest_snapshot
    ), "the ledger row must reference the persisted snapshot"


@pytest.mark.asyncio
async def test_unpinned_call_resolves_at_its_recorded_instant() -> None:
    """A later rate change must not reprice a call captured earlier."""
    latest_snapshot = _snapshot(input_token_rate=1_000_000)
    catalogue = _DriftingCatalogue(latest_snapshot=latest_snapshot)
    recorder = CostRecorder(
        ledger=RecordingLedger(pinned_snapshot_id=None),
        snapshots=RecordingSnapshots(snapshot=latest_snapshot),
        pricing_catalogue=catalogue,
        pricing_engine=PricingEngine(),
    )

    await recorder.record_provider_call(_provider_call_record())

    assert catalogue.resolved_at == ["2026-06-04T00:00:00Z"], (
        "an unpinned call must resolve at the instant it was captured"
    )


@pytest.mark.asyncio
async def test_cost_recorder_persists_snapshot_before_pinning() -> None:
    """The real pin method ensures the snapshot before writing the pin."""
    snapshot = _snapshot(input_token_rate=1_000_000)
    calls: list[tuple[str, PricingSnapshotId]] = []
    ledger = RecordingLedger(pinned_snapshot_id=None, calls=calls)
    snapshots = RecordingSnapshots(snapshot=snapshot, calls=calls)
    recorder = CostRecorder(
        ledger=ledger,
        snapshots=snapshots,
        pricing_catalogue=_DriftingCatalogue(latest_snapshot=snapshot),
        pricing_engine=PricingEngine(),
    )

    await recorder.pin_run_pricing(
        "run-pin-order",
        (
            CostProviderOperation(
                service_kind=PricedService.LLM,
                provider_name="openai",
                model="gpt-4o-mini",
                operation="chat_completions",
            ),
        ),
        BillingPeriodKey("2026-06"),
    )

    assert calls == [
        ("ensure", surrogate_snapshot_id(snapshot)),
        ("pin", surrogate_snapshot_id(snapshot)),
    ], f"the snapshot must be persisted before it is pinned; got {calls!r}"
