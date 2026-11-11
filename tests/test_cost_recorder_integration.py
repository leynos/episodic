"""Integration tests for the cost recorder against SQL persistence."""

import dataclasses as dc
import textwrap
import typing as typ

import pytest
import sqlalchemy as sa

from episodic.cost import BillingPeriodKey
from episodic.cost.pricing_snapshot import (
    PricedService,
    PricingSnapshot,
    PricingSubject,
)
from episodic.cost.storage import (
    CostLedgerEntryRecord,
    PricingSnapshotRecord,
    RunPricingPinRecord,
    SqlAlchemyCostLedgerStore,
    SqlAlchemyPricingSnapshotStore,
)
from tests.fixtures.cost import v1_pricing_snapshot

if typ.TYPE_CHECKING:
    import pathlib

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.cost.recorder import CostRecorder


_PINNED_RUN_ID = "workflow-run-pinned-rates"
_RATE_CARD_FILE = "openai-2026-06.yaml"
_NOW = "2026-06-04T00:00:00Z"


def _write_rate_card(directory: pathlib.Path, *, input_rate: int) -> None:
    """Write one v1 rate card whose input-token rate is settable."""
    (directory / _RATE_CARD_FILE).write_text(
        textwrap.dedent(
            f"""
            schema_version: 1
            service_kind: llm
            provider_name: openai
            model: gpt-4o-mini
            operation: chat_completions
            source_kind: provider_rate_card
            currency: USD
            rates:
              input_tokens:
                amount_minor: {input_rate}
                per_units: 1000000
                unit: token
              output_tokens:
                amount_minor: 1
                per_units: 1000000
                unit: token
            source_metadata:
              source_url: https://example.test/pricing
            retrieved_at: "2026-06-01T00:00:00Z"
            effective_from: "2026-06-01T00:00:00Z"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


@dc.dataclass(frozen=True, slots=True)
class _SingleSnapshotCatalogue:
    """Catalogue fake resolving one fixed snapshot."""

    snapshot: PricingSnapshot

    async def resolve(self, subject: PricingSubject) -> PricingSnapshot:
        """Return the fixture snapshot for any lookup."""
        _ = subject
        return self.snapshot


@pytest.mark.asyncio
async def test_cost_recorder_pins_on_a_fresh_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The real recorder persists the snapshot before the foreign-key pin."""
    from episodic.cost.engine import PricingEngine
    from episodic.cost.recorder import CostProviderOperation, CostRecorder

    async with session_factory() as session:
        recorder = CostRecorder(
            ledger=SqlAlchemyCostLedgerStore(session),
            snapshots=SqlAlchemyPricingSnapshotStore(session),
            pricing_catalogue=_SingleSnapshotCatalogue(v1_pricing_snapshot()),
            pricing_engine=PricingEngine(),
        )
        await recorder.pin_run_pricing(
            "workflow-run-fresh-pin",
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
        await session.commit()

    async with session_factory() as session:
        stored = (
            await session.execute(sa.select(sa.func.count(PricingSnapshotRecord.id)))
        ).scalar_one()
        pinned = (
            await session.execute(
                sa
                .select(PricingSnapshotRecord.content_hash)
                .join(
                    RunPricingPinRecord,
                    RunPricingPinRecord.pricing_snapshot_id == PricingSnapshotRecord.id,
                )
                .where(RunPricingPinRecord.workflow_run_id == "workflow-run-fresh-pin")
            )
        ).scalar_one()

    assert stored == 1, "pinning on a fresh database must persist the snapshot"
    assert pinned == v1_pricing_snapshot().content_hash, (
        "the pin must reference the persisted snapshot"
    )


def _build_pinned_run_recorder(
    session: AsyncSession,
    directory: pathlib.Path,
) -> CostRecorder:
    """Build a recorder whose catalogue reads the given directory."""
    from episodic.cost.engine import PricingEngine
    from episodic.cost.pricing_catalogue import FilePricingCatalogue
    from episodic.cost.recorder import CostRecorder

    return CostRecorder(
        ledger=SqlAlchemyCostLedgerStore(session),
        snapshots=SqlAlchemyPricingSnapshotStore(session),
        pricing_catalogue=FilePricingCatalogue(directory, now=lambda: _NOW),
        pricing_engine=PricingEngine(),
    )


async def _pin_rate_card_run(
    session_factory: async_sessionmaker[AsyncSession],
    directory: pathlib.Path,
) -> None:
    """Pin the run through a real recorder so the snapshot reaches the database."""
    from episodic.cost.recorder import CostProviderOperation

    async with session_factory() as session:
        recorder = _build_pinned_run_recorder(session, directory)
        await recorder.pin_run_pricing(
            _PINNED_RUN_ID,
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
        await session.commit()


async def _record_pinned_provider_call(
    session_factory: async_sessionmaker[AsyncSession],
    directory: pathlib.Path,
) -> int:
    """Record one pinned provider call and return its persisted cost."""
    from episodic.cost.ports import (
        IdempotencyKey,
        PricingModel,
        UsageSource,
    )
    from episodic.cost.recorder import ProviderCallRecord

    async with session_factory() as session:
        recorder = _build_pinned_run_recorder(session, directory)
        await recorder.record_provider_call(
            ProviderCallRecord(
                idempotency_key=IdempotencyKey(
                    "run:pinned:node:draft:call:1:attempt:0"
                ),
                parent_cost_entry_id=None,
                provider_type="llm",
                provider_name="openai",
                model="gpt-4o-mini",
                workflow_node="draft",
                operation="chat_completions",
                usage={"input_tokens": 3},
                usage_source=UsageSource.PROVIDER,
                usage_complete=True,
                pricing_model=PricingModel.PAYG,
                retry_attempt=0,
                billing_period_key=BillingPeriodKey("2026-06"),
                workflow_run_id=_PINNED_RUN_ID,
                recorded_at=_NOW,
            ),
        )
        await session.commit()

    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(CostLedgerEntryRecord.computed_cost_minor).where(
                    CostLedgerEntryRecord.workflow_run_id == _PINNED_RUN_ID
                )
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_pinned_call_prices_from_persisted_snapshot_after_file_removal(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: pathlib.Path,
) -> None:
    """A pinned run keeps its rates after its rate card file is deleted."""
    _write_rate_card(tmp_path, input_rate=1_000_000)
    await _pin_rate_card_run(session_factory, tmp_path)
    (tmp_path / _RATE_CARD_FILE).unlink()

    cost = await _record_pinned_provider_call(session_factory, tmp_path)

    assert cost == 3, (
        "a pinned call must price from the persisted snapshot, not the deleted file"
    )


@pytest.mark.asyncio
async def test_pinned_call_prices_from_persisted_snapshot_after_file_edit(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: pathlib.Path,
) -> None:
    """An in-place rate-card edit must not reprice an already pinned run."""
    _write_rate_card(tmp_path, input_rate=1_000_000)
    await _pin_rate_card_run(session_factory, tmp_path)
    _write_rate_card(tmp_path, input_rate=9_000_000)

    cost = await _record_pinned_provider_call(session_factory, tmp_path)

    assert cost == 3, (
        "a pinned call must use the stored rates, not the edited rate card"
    )
