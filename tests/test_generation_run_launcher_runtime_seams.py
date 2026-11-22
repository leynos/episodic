"""Tests for launcher seams that callers replace at runtime.

The launcher's collaborators were writable fields before the component split,
and ``source_from_document`` was resolved from the launcher module when a run
hydrated. These tests pin both behaviours so the injected components cannot
silently freeze a value the base once read at use time.
"""

import dataclasses as dc
import datetime as dt
import typing as typ

import pytest

import episodic.generation.launcher as launcher_module
from episodic.canonical.domain import GenerationRunStatus, SourceDocument
from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.launcher_support import GenerationSourceLimits
from episodic.observability import RecordingTracer
from tests.generation_run_launcher_support import (
    LauncherOptions,
    RecordingCostRecorder,
    RecordingDraftGenerator,
    draft_result,
    launch_and_load_run,
    launcher,
    prepare_pending_run,
    valid_tei,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.generation.draft_script import (
        DraftScriptRequest,
        DraftScriptResult,
        DraftScriptSource,
    )


@dc.dataclass(slots=True)
class _RecordingMetrics:
    """Capture bounded launcher metrics for assertions."""

    counters: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)
    values: list[tuple[str, float, dict[str, str]]] = dc.field(default_factory=list)

    def increment_counter(self, name: str, *, labels: cabc.Mapping[str, str]) -> None:
        """Capture one counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture one latency observation."""
        _ = (name, value, labels)

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture one scalar observation."""
        self.values.append((name, value, dict(labels)))


@dc.dataclass(slots=True)
class _FailingDraftGenerator:
    """Draft generator fake that raises the configured exception."""

    error: Exception

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Raise the configured generation error."""
        _ = request
        raise self.error


@pytest.mark.asyncio
async def test_launcher_observes_tracer_assigned_after_construction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A tracer assigned after construction should still record the run's span."""
    run_id, _ = await prepare_pending_run(session_factory)
    run_launcher = launcher(
        session_factory,
        _FailingDraftGenerator(RuntimeError("boom")),
    )
    tracer = RecordingTracer()
    run_launcher.tracer = tracer

    run, events = await launch_and_load_run(session_factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.FAILED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert tracer.spans, "expected the late-assigned tracer to record the run span"
    assert tracer.spans[0].attributes["failure_category"] == "unexpected", tracer.spans


@pytest.mark.asyncio
async def test_launcher_observes_metrics_assigned_after_construction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Metrics assigned after construction should still receive run observations."""
    run_id, _ = await prepare_pending_run(session_factory)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )
    metrics = _RecordingMetrics()
    run_launcher.metrics = metrics

    run, events = await launch_and_load_run(session_factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert (
        "generation_run_terminal_total",
        {"status": GenerationRunStatus.SUCCEEDED.value, "error_category": "none"},
    ) in metrics.counters, metrics.counters


@pytest.mark.asyncio
async def test_launcher_observes_success_emitted_after_construction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A cost recorder assigned after construction should record the run's cost."""
    run_id, _ = await prepare_pending_run(session_factory)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )
    cost_recorder = RecordingCostRecorder()
    run_launcher.cost_recorder_factory = lambda uow: cost_recorder

    run, events = await launch_and_load_run(session_factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert cost_recorder.provider_calls, "expected the late cost recorder to be used"
    assert cost_recorder.finalized_runs == [(str(run_id), "draft")], (
        f"run {run_id} finalized runs={cost_recorder.finalized_runs!r}"
    )


@pytest.mark.asyncio
async def test_launcher_observes_draft_generator_assigned_after_construction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A draft generator assigned after construction should generate the draft."""
    run_id, _ = await prepare_pending_run(session_factory)
    run_launcher = launcher(
        session_factory,
        _FailingDraftGenerator(RuntimeError("original generator must not run")),
    )
    replacement = RecordingDraftGenerator(draft_result(valid_tei()))
    run_launcher.draft_generator = typ.cast("typ.Any", replacement)

    run, events = await launch_and_load_run(session_factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert replacement.requests, "expected the late generator to be invoked"


@pytest.mark.asyncio
async def test_launcher_applies_source_limits_assigned_after_construction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Source limits replaced after construction should bound the next run."""
    run_id, _ = await prepare_pending_run(session_factory)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )
    run_launcher.source_limits = GenerationSourceLimits(max_source_bytes=1)

    run, events = await launch_and_load_run(session_factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.FAILED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert events[-1].payload["error_category"] == "generation.source_limit", (
        f"run {run_id} final event={events[-1]!r}"
    )


@pytest.mark.asyncio
async def test_launcher_keeps_scheduler_state_across_collaborator_changes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Replacing observability mid-flight should not lose admitted run state."""
    run_id, _ = await prepare_pending_run(session_factory)
    generator = RecordingDraftGenerator(draft_result(valid_tei()))
    run_launcher = launcher(
        session_factory,
        generator,
        options=LauncherOptions(max_concurrency=1, max_pending_runs=1),
    )

    await run_launcher.launch(run_id)
    run_launcher.metrics = _RecordingMetrics()
    run_launcher.tracer = RecordingTracer()
    await run_launcher.drain()

    assert run_launcher.scheduled_run_count == 0, run_launcher.scheduled_run_count
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
    assert run is not None, f"run {run_id} was not persisted"
    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}; quality_mode={QualityMode.DRAFT_WITHOUT_QA}"
    )


@pytest.mark.asyncio
async def test_launcher_uses_source_from_document_patched_after_construction(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patching the launcher module's loader after construction must take effect."""
    run_id, _ = await prepare_pending_run(session_factory)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
    )
    seen: list[str] = []
    real_source_from_document = launcher_module.source_from_document

    async def recording_source_from_document(
        document: SourceDocument,
        object_store: ObjectStorePort | None,
        limits: GenerationSourceLimits | None = None,
        *,
        remaining_aggregate_bytes: int | None = None,
    ) -> DraftScriptSource:
        """Record the patched call and delegate to the real loader."""
        seen.append(str(document.id))
        return await real_source_from_document(
            document,
            object_store,
            limits,
            remaining_aggregate_bytes=remaining_aggregate_bytes,
        )

    monkeypatch.setattr(
        launcher_module,
        "source_from_document",
        recording_source_from_document,
    )

    run, events = await launch_and_load_run(session_factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert seen, "expected the post-construction patch to load the run's sources"
    assert events[-1].occurred_at >= dt.datetime(2026, 1, 1, tzinfo=dt.UTC), events
