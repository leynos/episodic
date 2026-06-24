"""Support fixtures for generation-run launcher tests."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import datetime as dt
import hashlib
import typing as typ
import uuid

from episodic.canonical.domain import (
    GenerationRun,
    GenerationRunStatus,
    IngestionJob,
    IngestionStatus,
    IntakeState,
    SeriesProfile,
)
from episodic.canonical.generation_persistence import (
    EpisodeMaterialisationRequest,
    materialise_episode_from_ingestion,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.ingestion_sources import AttachmentKind, IngestionJobSource
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.cost.ports import BillingPeriodKey, CostLedgerEntryId, UsageSource
from episodic.generation.draft_script import (
    DraftScriptRequest,
    DraftScriptResult,
)
from episodic.generation.launcher import InProcessGenerationRunLauncher
from episodic.llm import LLMUsage, ProviderCallUsage

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.cost.recorder import CostProviderOperation, ProviderCallRecord

NOW = dt.datetime(2026, 6, 24, 12, 0, tzinfo=dt.UTC)


@dc.dataclass(slots=True)
class RecordingDraftGenerator:
    """Draft generator fake that returns one configured result."""

    result: DraftScriptResult
    requests: list[DraftScriptRequest] = dc.field(default_factory=list)

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Capture the request and return the configured result."""
        self.requests.append(request)
        return self.result


@dc.dataclass(slots=True)
class FailingDraftGenerator:
    """Draft generator fake that raises the configured exception."""

    error: Exception

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Raise the configured generation error."""
        _ = request
        raise self.error


class BlockingDraftGenerator:
    """Draft generator fake that blocks until the task is cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Block until cancelled by the launcher shutdown hook."""
        _ = request
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError


@dc.dataclass(slots=True)
class RecordingCostRecorder:
    """Cost recorder fake that captures provider calls and roll-ups."""

    provider_calls: list[ProviderCallRecord] = dc.field(default_factory=list)
    finalized_runs: list[tuple[str, str | None]] = dc.field(default_factory=list)

    @staticmethod
    async def pin_run_pricing(
        workflow_run_id: str,
        providers: tuple[CostProviderOperation, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Accept pricing pins for the fake recorder."""
        _ = (workflow_run_id, providers, billing_period_key)

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> CostLedgerEntryId:
        """Capture one provider-call record."""
        self.provider_calls.append(record)
        return CostLedgerEntryId(f"entry:{len(self.provider_calls)}")

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> CostLedgerEntryId:
        """Capture final run roll-up requests."""
        self.finalized_runs.append((workflow_run_id, workflow_node))
        return CostLedgerEntryId("entry:rollup")


def _clock() -> dt.datetime:
    """Return the frozen launcher timestamp."""
    return NOW


def _series_profile() -> SeriesProfile:
    """Return a series profile fixture."""
    return SeriesProfile(
        id=uuid.UUID("00000000-0000-0000-0000-000000000201"),
        slug="bridgewater",
        title="Bridgewater",
        description=None,
        configuration={},
        guardrails={},
        created_at=NOW,
        updated_at=NOW,
    )


def _ingestion_job(series_profile_id: uuid.UUID) -> IngestionJob:
    """Return a ready intake job fixture."""
    return IngestionJob(
        id=uuid.UUID("00000000-0000-0000-0000-000000000301"),
        series_profile_id=series_profile_id,
        target_episode_id=None,
        status=IngestionStatus.PENDING,
        requested_at=NOW,
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
        intake_state=IntakeState.READY_FOR_GENERATION,
    )


def _source(job_id: uuid.UUID) -> IngestionJobSource:
    """Return one source attachment carrying text for generation."""
    return IngestionJobSource(
        id=uuid.UUID("00000000-0000-0000-0000-000000000401"),
        ingestion_job_id=job_id,
        attachment_kind=AttachmentKind.SOURCE_URI,
        upload_id=None,
        source_uri="https://example.test/source.md",
        source_type="research_brief",
        weight=1.0,
        metadata={"content": "Bridgewater launch source text."},
        created_at=NOW,
    )


def draft_result(tei_xml: str) -> DraftScriptResult:
    """Return a generated draft result with provider usage."""
    return DraftScriptResult(
        tei_xml=tei_xml,
        content_hash=f"sha256:{hashlib.sha256(tei_xml.encode()).hexdigest()}",
        usage=LLMUsage(input_tokens=10, output_tokens=20, total_tokens=30),
        model="gpt-4o-mini",
        provider_response_id="resp-draft-1",
        finish_reason="stop",
        provider_call_usage=ProviderCallUsage(
            usage_metrics={"input_tokens": 10, "output_tokens": 20},
            usage_source=UsageSource.PROVIDER,
            usage_complete=True,
            provider_response_id="resp-draft-1",
            finish_reason="stop",
            started_at=NOW.isoformat(),
            latency_ms=125,
        ),
    )


def valid_tei() -> str:
    """Return valid generated TEI for launcher tests."""
    return (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Bridgewater Futures</title></fileDesc></teiHeader>"
        '<text><body><u who="Host">Welcome.</u></body></text></TEI>'
    )


def _run(episode_id: uuid.UUID, source_bundle_id: uuid.UUID) -> GenerationRun:
    """Return a pending no-QA generation run."""
    return GenerationRun(
        id=uuid.UUID("00000000-0000-0000-0000-000000000501"),
        episode_id=episode_id,
        source_bundle_id=source_bundle_id,
        actor="editor@example.test",
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={},
        configuration={},
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="Vertical slice draft.",
    )


async def prepare_pending_run(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Persist a ready episode and pending generation run."""
    series = _series_profile()
    job = _ingestion_job(series.id)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.flush()
        await uow.ingestion_jobs.add(job)
        await uow.ingestion_job_sources.add(_source(job.id))
        episode = await materialise_episode_from_ingestion(
            uow,
            EpisodeMaterialisationRequest(
                ingestion_job_id=job.id,
                title="Bridgewater Futures",
                clock=_clock,
            ),
        )
        run = _run(episode.id, job.id)
        await uow.generation_runs.create_run(run)
        await uow.commit()
    return run.id, episode.id


def launcher(
    factory: async_sessionmaker[AsyncSession],
    generator: object,
    cost_recorder: RecordingCostRecorder | None = None,
) -> InProcessGenerationRunLauncher:
    """Build a launcher for tests."""
    return InProcessGenerationRunLauncher(
        uow_factory=lambda: SqlAlchemyUnitOfWork(factory),
        draft_generator=typ.cast("typ.Any", generator),
        cost_recorder_factory=(
            None if cost_recorder is None else lambda uow: cost_recorder
        ),
        clock=_clock,
    )
