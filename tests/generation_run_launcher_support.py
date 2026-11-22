"""Support fixtures for generation-run launcher tests."""

import asyncio
import dataclasses as dc
import datetime as dt
import hashlib
import typing as typ
import uuid

from episodic.canonical.domain import (
    GenerationEvent,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.canonical.generation_persistence import (
    EpisodeMaterialisationRequest,
    materialise_episode_from_ingestion,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.cost.ports import BillingPeriodKey, CostLedgerEntryId, UsageSource
from episodic.generation.draft_script import (
    DraftScriptGenerator,
    DraftScriptRequest,
    DraftScriptResult,
)
from episodic.generation.launcher import InProcessGenerationRunLauncher
from episodic.llm import LLMUsage, ProviderCallUsage
from episodic.orchestration import LangGraphContentGenerationGraph
from tests.generation_run_launcher_seed_support import (
    _clock,
    _ingestion_job,
    _presenter_sets,
    _series_profile,
    _source,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.cost.recorder import CostProviderOperation, ProviderCallRecord

NOW = dt.datetime(2026, 6, 24, 12, 0, tzinfo=dt.UTC)


@dc.dataclass(frozen=True, slots=True)
class LauncherOptions:
    """Construction options for a test launcher.

    Attributes
    ----------
    max_concurrency : int
        Execution permits.
    max_pending_runs : int
        Additional admitted runs beyond the execution permits.
    evaluator_set : QualityEvaluatorSet
        Evaluators the injected content-generation graph uses. The default
        empty set accepts only no-QA runs, like production until 4.4.2.
    """

    max_concurrency: int = 4
    max_pending_runs: int = 16
    evaluator_set: QualityEvaluatorSet = dc.field(
        default_factory=lambda: QualityEvaluatorSet(())
    )


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
        """Create the event that signals when generation has started."""
        self.started = asyncio.Event()

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Block until cancelled by the launcher shutdown hook."""
        _ = request
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError


class ReleasableDraftGenerator:
    """Draft generator fake that completes when the test releases it."""

    def __init__(self, result: DraftScriptResult) -> None:
        """Store the draft result and create the start and release events."""
        self.result = result
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Wait for the test and then return the configured draft."""
        _ = request
        self.started.set()
        await self.release.wait()
        return self.result


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


async def launch_and_load_run(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    run_launcher: InProcessGenerationRunLauncher,
) -> tuple[GenerationRun, tuple[GenerationEvent, ...]]:
    """Launch a run and return its persisted terminal state and events.

    Parameters
    ----------
    factory : async_sessionmaker[AsyncSession]
        Session factory bound to the test database.
    run_id : uuid.UUID
        Identifier of the pending run to launch.
    run_launcher : InProcessGenerationRunLauncher
        Launcher under test.

    Returns
    -------
    tuple[GenerationRun, tuple[GenerationEvent, ...]]
        Persisted terminal run state and the events recorded for it.

    Raises
    ------
    LookupError
        If the run was not persisted or could not be loaded.
    """
    await run_launcher.launch(run_id)
    await run_launcher.drain()
    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        if run is None:
            msg = f"run {run_id} was not persisted"
            raise LookupError(msg)
        events = await uow.generation_runs.list_events(run_id)
    return run, events


async def _prepare_pending_run(
    factory: async_sessionmaker[AsyncSession],
    build_run: cabc.Callable[[uuid.UUID, uuid.UUID], GenerationRun],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Persist a ready episode and a pending run built by ``build_run``.

    Parameters
    ----------
    factory : async_sessionmaker[AsyncSession]
        Session factory bound to the test database.
    build_run : collections.abc.Callable[[uuid.UUID, uuid.UUID], GenerationRun]
        Builder that receives the materialised episode and source-bundle ids.

    Returns
    -------
    tuple[uuid.UUID, uuid.UUID]
        The persisted run id and episode id.
    """
    series = _series_profile()
    job = _ingestion_job(series.id)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.flush()
        await uow.ingestion_jobs.add(job)
        await uow.ingestion_job_sources.add(_source(job.id))
        for document, revision, binding in _presenter_sets(series.id):
            await uow.reference_documents.add(document)
            await uow.reference_document_revisions.add(revision)
            await uow.flush()
            await uow.reference_bindings.add(binding)
        episode = await materialise_episode_from_ingestion(
            uow,
            EpisodeMaterialisationRequest(
                ingestion_job_id=job.id,
                title="Bridgewater Futures",
                clock=_clock,
            ),
        )
        run = build_run(episode.id, job.id)
        await uow.generation_runs.create_run(run)
        await uow.commit()
    return run.id, episode.id


async def prepare_pending_run(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Persist a ready episode and a pending no-QA generation run."""
    return await _prepare_pending_run(factory, _run)


def launcher(
    factory: async_sessionmaker[AsyncSession],
    generator: DraftScriptGenerator,
    cost_recorder: RecordingCostRecorder | None = None,
    *,
    options: LauncherOptions | None = None,
) -> InProcessGenerationRunLauncher:
    """Build a launcher for tests."""
    effective_options = LauncherOptions() if options is None else options
    graph = LangGraphContentGenerationGraph(effective_options.evaluator_set)
    return InProcessGenerationRunLauncher(
        uow_factory=lambda: SqlAlchemyUnitOfWork(factory),
        draft_generator=generator,
        content_graph=graph,
        cost_recorder_factory=(
            None if cost_recorder is None else lambda uow: cost_recorder
        ),
        clock=_clock,
        max_concurrency=effective_options.max_concurrency,
        max_pending_runs=effective_options.max_pending_runs,
    )
