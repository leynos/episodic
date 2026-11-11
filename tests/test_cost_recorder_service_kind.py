"""Service-kind handling in the cost recorder's subject resolution."""

import dataclasses as dc

import pytest

from episodic.cost.engine import PricingEngine
from episodic.cost.ports import (
    BillingPeriodKey,
    IdempotencyKey,
    PricingModel,
    UsageSource,
)
from episodic.cost.pricing_snapshot import (
    PricedService,
    PricingSnapshot,
    PricingSubject,
)
from episodic.cost.recorder import (
    CostProviderOperation,
    CostRecorder,
    ProviderCallRecord,
)
from tests.fixtures.cost import (
    RecordingLedger,
    RecordingSnapshots,
    v1_pricing_snapshot,
)


@dc.dataclass(slots=True)
class _RecordingCatalogue:
    """Catalogue fake recording the subjects it is asked to price."""

    snapshot: PricingSnapshot
    subjects: list[PricingSubject] = dc.field(default_factory=list)

    async def resolve(self, subject: PricingSubject) -> PricingSnapshot:
        """Capture the subject and return the configured snapshot."""
        self.subjects.append(subject)
        return self.snapshot


def _record(provider_type: str = "llm") -> ProviderCallRecord:
    """Build a provider-call record with the supplied provider type."""
    return ProviderCallRecord(
        idempotency_key=IdempotencyKey("run:abc:node:planner:call:1:attempt:0"),
        parent_cost_entry_id=None,
        provider_type=provider_type,
        provider_name="openai",
        model="gpt-4o-mini",
        workflow_node="planner",
        operation="chat_completions",
        usage={"input_tokens": 1},
        usage_source=UsageSource.PROVIDER,
        usage_complete=True,
        pricing_model=PricingModel.PAYG,
        retry_attempt=0,
        billing_period_key=BillingPeriodKey("2026-06"),
        workflow_run_id="run-abc",
        recorded_at="2026-06-04T00:00:00Z",
    )


def _recorder(
    catalogue: _RecordingCatalogue,
    ledger: RecordingLedger,
) -> CostRecorder:
    """Build a recorder wired to the supplied fakes."""
    return CostRecorder(
        ledger=ledger,
        snapshots=RecordingSnapshots(snapshot=v1_pricing_snapshot()),
        pricing_catalogue=catalogue,
        pricing_engine=PricingEngine(),
    )


@pytest.mark.asyncio
async def test_unpinned_call_derives_service_kind_from_provider_type() -> None:
    """A provider-call record's provider type selects the service kind."""
    catalogue = _RecordingCatalogue(snapshot=v1_pricing_snapshot())

    await _recorder(catalogue, RecordingLedger()).record_provider_call(_record("llm"))

    assert catalogue.subjects[0].service_kind is PricedService.LLM, (
        "an LLM provider type must resolve to the LLM service kind"
    )


@pytest.mark.asyncio
async def test_unknown_provider_type_is_rejected() -> None:
    """An unrecognized provider type cannot select a service kind."""
    catalogue = _RecordingCatalogue(snapshot=v1_pricing_snapshot())

    with pytest.raises(ValueError, match="audio"):
        await _recorder(catalogue, RecordingLedger()).record_provider_call(
            _record("audio")
        )

    assert not catalogue.subjects, (
        "a rejected provider type must not query the catalogue"
    )


@pytest.mark.asyncio
async def test_pin_run_pricing_uses_the_operation_service_kind() -> None:
    """Pinned operations name their service kind explicitly."""
    catalogue = _RecordingCatalogue(snapshot=v1_pricing_snapshot())

    await _recorder(catalogue, RecordingLedger()).pin_run_pricing(
        "run-pin",
        (
            CostProviderOperation(
                service_kind=PricedService.TTS,
                provider_name="tts-vendor",
                model="voice-v1",
                operation="synthesize",
            ),
        ),
        BillingPeriodKey("2026-06"),
    )

    assert catalogue.subjects[0].service_kind is PricedService.TTS, (
        "a pinned operation must use its declared service kind"
    )
