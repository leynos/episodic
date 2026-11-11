"""Shared state and helpers for the pricing-snapshot behavioural tests.

The shapes here keep the step module declarative: writing rate cards, building
a real recorder over a real catalogue, and persisting or reading snapshots all
happen once rather than per scenario.
"""

import dataclasses as dc
import datetime as dt
import textwrap
import typing as typ
import uuid

import sqlalchemy as sa

from episodic.cost.engine import PricingEngine, PricingRequest
from episodic.cost.ports import IdempotencyKey, PricingModel, UsageSource
from episodic.cost.pricing_catalogue import FilePricingCatalogue
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    PricingSubject,
    SourceDocument,
    UsageUnit,
)
from episodic.cost.primitives import (
    BillingPeriodKey,
    CurrencyCode,
    PricingSnapshotId,
    PricingSourceKind,
)
from episodic.cost.recorder import (
    CostProviderOperation,
    CostRecorder,
    ProviderCallRecord,
)
from episodic.cost.storage import (
    CostLedgerEntryRecord,
    PricingSnapshotRecord,
    SqlAlchemyCostLedgerStore,
    SqlAlchemyPricingSnapshotStore,
)
from episodic.llm import LLMRequest
from episodic.llm.openai_api.adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import pathlib
    import subprocess

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]

NOW = "2026-06-04T00:00:00Z"
_INSTANT = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
BILLING_PERIOD = BillingPeriodKey("2026-06")
LLM_RUN_ID = "bdd-pinned-run"
REVISED_RUN_ID = "bdd-pinned-run-after-revision"
LLM_OPERATION = CostProviderOperation(
    service_kind=PricedService.LLM,
    provider_name="openai",
    model="gpt-4o-mini",
    operation="chat_completions",
)
TTS_SUBJECT = PricingSubject(
    service_kind=PricedService.TTS,
    provider_name="acme",
    model="voice-1",
    operation="tts",
)
TTS_USAGE = {
    "input_characters": 2_000_000,
    "output_audio_milliseconds": 120_000,
}
SLA4OAI_DOCUMENT = """\
sla4oai: "0.10.0"
context:
  id: pedante-helper
  name: Pedante helper service
plans:
  - plan: standard
    guarantees:
      - name: response_quality
        target: 0.99
"""


@dc.dataclass(frozen=True, slots=True)
class CallOptions:
    """Optional identity and provenance for one recorded provider call."""

    call_label: str
    model: str = "gpt-4o-mini"
    usage_source: UsageSource = UsageSource.PROVIDER


@dc.dataclass(slots=True)
class RecordedCall:
    """Cost and snapshot identity of one recorded provider call."""

    cost_minor: int
    pricing_snapshot_id: uuid.UUID


@dc.dataclass(slots=True)
class PricingSnapshotContext:
    """State shared between the pricing-snapshot BDD steps."""

    directory: pathlib.Path
    session_factory: SessionFactory
    run_id: str = LLM_RUN_ID
    usage: dict[str, int] = dc.field(default_factory=dict)
    recorded: RecordedCall | None = None
    repriced_cost_minor: int | None = None
    revised_run_cost_minor: int | None = None
    snapshot: PricingSnapshot | None = None
    stored: PricingSnapshot | None = None
    stored_snapshot_id: PricingSnapshotId | None = None
    altered_hash: str | None = None
    read_error: Exception | None = None
    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    stderr_file: typ.TextIO | None = None


def write_llm_card(directory: pathlib.Path, *, cached_minor: str = "8") -> None:
    """Write the gpt-4o-mini rate card with a settable cached-input rate."""
    (directory / "openai-2026-05.yaml").write_text(
        textwrap.dedent(
            f"""\
            schema_version: 1
            service_kind: llm
            provider_name: openai
            model: gpt-4o-mini
            operation: chat_completions
            source_kind: provider_rate_card
            currency: USD
            rates:
              input_tokens:
                amount_minor: "15"
                per_units: 1000000
                unit: token
              output_tokens:
                amount_minor: "60"
                per_units: 1000000
                unit: token
              cached_input_tokens:
                amount_minor: "{cached_minor}"
                per_units: 1000000
                unit: token
            source_metadata:
              source_url: https://example.test/pricing
            retrieved_at: "2026-05-01T00:00:00Z"
            effective_from: "2026-05-01T00:00:00Z"
            """
        ),
        encoding="utf-8",
    )


def write_tts_card(directory: pathlib.Path, *, include_audio: bool = True) -> None:
    """Write the TTS rate card, optionally adding the audio-duration rate."""
    audio_rate = (
        "  output_audio_milliseconds:\n"
        '    amount_minor: "5"\n'
        "    per_units: 60000\n"
        "    unit: millisecond\n"
        if include_audio
        else ""
    )
    (directory / "acme-tts.yaml").write_text(
        textwrap.dedent(
            """\
            schema_version: 1
            service_kind: tts
            provider_name: acme
            model: voice-1
            operation: tts
            source_kind: provider_rate_card
            currency: USD
            rates:
              input_characters:
                amount_minor: "1500"
                per_units: 1000000
                unit: character
            """
        )
        + audio_rate
        + textwrap.dedent(
            """\
            source_metadata:
              source_url: https://example.test/tts-pricing
            retrieved_at: "2026-05-01T00:00:00Z"
            effective_from: "2026-05-01T00:00:00Z"
            """
        ),
        encoding="utf-8",
    )


def build_catalogue(directory: pathlib.Path) -> FilePricingCatalogue:
    """Build a fresh catalogue so a revised card is reloaded."""
    return FilePricingCatalogue(directory, now=lambda: NOW)


def build_recorder(session: AsyncSession, directory: pathlib.Path) -> CostRecorder:
    """Build a recorder over the real stores and the given card directory."""
    return CostRecorder(
        ledger=SqlAlchemyCostLedgerStore(session),
        snapshots=SqlAlchemyPricingSnapshotStore(session),
        pricing_catalogue=build_catalogue(directory),
        pricing_engine=PricingEngine(),
    )


async def pin_llm_run(
    session_factory: SessionFactory,
    directory: pathlib.Path,
    run_id: str,
) -> None:
    """Pin the gpt-4o-mini operation for one run from the current card."""
    async with session_factory() as session:
        await build_recorder(session, directory).pin_run_pricing(
            run_id,
            (LLM_OPERATION,),
            BILLING_PERIOD,
        )
        await session.commit()


async def record_llm_call(
    context: PricingSnapshotContext,
    run_id: str,
    usage: cabc.Mapping[str, int],
    options: CallOptions,
) -> RecordedCall:
    """Record one call through the real recorder and return its cost."""
    record = ProviderCallRecord(
        idempotency_key=IdempotencyKey(f"run:{run_id}:call:{options.call_label}"),
        parent_cost_entry_id=None,
        provider_type=PricedService.LLM.value,
        provider_name="openai",
        model=options.model,
        workflow_node="bdd",
        operation="chat_completions",
        usage=dict(usage),
        usage_source=options.usage_source,
        usage_complete=True,
        pricing_model=PricingModel.PAYG,
        retry_attempt=0,
        billing_period_key=BILLING_PERIOD,
        workflow_run_id=run_id,
        recorded_at=NOW,
    )
    async with context.session_factory() as session:
        entry_id = await build_recorder(
            session, context.directory
        ).record_provider_call(record)
        await session.commit()
    return await _recorded_call(context.session_factory, entry_id)


async def record_completion(
    context: PricingSnapshotContext,
) -> tuple[dict[str, int], RecordedCall]:
    """Call the completion endpoint and record the usage the provider reports."""
    config = OpenAICompatibleLLMConfig(base_url=context.base_url, api_key="test-key")
    async with OpenAICompatibleLLMAdapter(config=config) as adapter:
        response = await adapter.generate(
            LLMRequest(model="gpt-4o-mini", prompt="price this call")
        )
    usage = response.provider_call_usage
    assert usage is not None, "the provider must report usage for pricing"
    metrics = dict(usage.usage_metrics)
    recorded = await record_llm_call(
        context,
        context.run_id,
        metrics,
        CallOptions(
            call_label="vidaimock",
            model=response.model,
            usage_source=usage.usage_source,
        ),
    )
    return metrics, recorded


async def _recorded_call(
    session_factory: SessionFactory,
    entry_id: str,
) -> RecordedCall:
    """Read back the cost and snapshot identity of one ledger entry."""
    async with session_factory() as session:
        row = (
            await session.execute(
                sa.select(
                    CostLedgerEntryRecord.computed_cost_minor,
                    CostLedgerEntryRecord.pricing_snapshot_id,
                ).where(CostLedgerEntryRecord.id == uuid.UUID(str(entry_id)))
            )
        ).one()
    return RecordedCall(cost_minor=int(row[0]), pricing_snapshot_id=row[1])


async def reprice_from_stored_snapshot(
    session_factory: SessionFactory,
    snapshot_id: uuid.UUID,
    usage: cabc.Mapping[str, int],
    operation: str,
) -> int:
    """Price the same usage from the persisted snapshot, not the card."""
    async with session_factory() as session:
        stored = await SqlAlchemyPricingSnapshotStore(session).get(
            PricingSnapshotId(str(snapshot_id))
        )
    return PricingEngine.price(
        stored,
        PricingRequest(usage=dict(usage), operation=operation),
    ).computed_cost_minor


async def persist_and_read(
    session_factory: SessionFactory,
    snapshot: PricingSnapshot,
) -> tuple[PricingSnapshotId, PricingSnapshot]:
    """Persist one snapshot and read it back through a fresh session."""
    async with session_factory() as session:
        ensured = await SqlAlchemyPricingSnapshotStore(session).ensure(snapshot)
        await session.commit()
    async with session_factory() as session:
        stored = await SqlAlchemyPricingSnapshotStore(session).get(
            ensured.pricing_snapshot_id
        )
    return ensured.pricing_snapshot_id, stored


async def tamper_stored_rates(
    session_factory: SessionFactory,
    snapshot_id: PricingSnapshotId,
) -> None:
    """Alter a stored snapshot's rates behind the content hash."""
    async with session_factory() as session:
        await session.execute(
            sa
            .update(PricingSnapshotRecord)
            .where(PricingSnapshotRecord.id == uuid.UUID(str(snapshot_id)))
            .values(
                rates={
                    "input_tokens": {
                        "amount_minor": 99,
                        "per_units": 1,
                        "unit": "token",
                    }
                }
            )
        )
        await session.commit()


async def read_stored_snapshot(
    session_factory: SessionFactory,
    snapshot_id: PricingSnapshotId,
) -> PricingSnapshot:
    """Read one stored snapshot, verifying its content hash."""
    async with session_factory() as session:
        return await SqlAlchemyPricingSnapshotStore(session).get(snapshot_id)


def helper_plan_snapshot(document: str) -> PricingSnapshot:
    """Build the helper-service snapshot carrying an SLA4OAI document."""
    return PricingSnapshot(
        service_kind=PricedService.HELPER_SERVICE,
        provider_name="pedante",
        model="plans",
        operation="resolve",
        source_kind=PricingSourceKind.SLA4OAI_PLAN,
        currency=CurrencyCode("USD"),
        rates={"requests": MeteredRate.reduced(1, 1, UsageUnit.REQUEST)},
        retrieved_at=_INSTANT,
        effective_from=_INSTANT,
        source_document=SourceDocument(
            media_type="application/yaml",
            content=document,
        ),
    )
