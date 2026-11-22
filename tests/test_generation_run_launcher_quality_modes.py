"""Launcher tests for QA-gated runs (INV-9, INV-10).

Each quality-mode cell runs against py-pglite with a deterministic evaluator
double. The assertions cover ordered publication by a single writer, the
terminal event, QA status, costs, and bounded metrics. Cancellation tests use
fakes gated on ``asyncio.Event`` so the blocking point is observed before
shutdown.
"""

import asyncio
import dataclasses as dc
import typing as typ

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.draft_script import DraftScriptTransientProviderError
from episodic.observability import RecordingTracer
from tests.generation_run_launcher_observation_support import (
    RecordingMetrics,
)
from tests.generation_run_launcher_support import (
    FailingDraftGenerator,
    LauncherOptions,
    RecordingCostRecorder,
    RecordingDraftGenerator,
    draft_result,
    launcher,
    prepare_pending_qa_gated_run,
    prepare_pending_run,
    valid_tei,
)
from tests.generation_run_quality_support import (
    BlockingQualityEvaluator,
    TaskNameAssertingUnitOfWork,
    assert_off_task_append_is_rejected,
    failing_evaluator,
    inconclusive_evaluator,
    passing_evaluator,
    raising_evaluator,
)

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_METRIC_GATE = "generation_run_qa_gate_total"
_METRIC_EVALUATOR_ERRORS = "generation_run_qa_evaluator_errors_total"
_METRIC_DRAFT_ERRORS = "generation_run_draft_errors_total"


async def _load(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> tuple[GenerationRun, list[tuple[str, dict[str, object]]], int]:
    """Load a run, its event kinds and payloads, and the episode TEI revision."""
    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)
    assert run is not None, f"run {run_id} was not persisted"
    async with SqlAlchemyUnitOfWork(factory) as uow:
        episode = await uow.episodes.get(run.episode_id)
    assert episode is not None, f"episode {run.episode_id} was not persisted"
    return run, [(event.kind, event.payload) for event in events], episode.tei_revision


def _counter_sum(metrics: RecordingMetrics, name: str) -> int:
    """Count matching counter observations."""
    return sum(
        1
        for observation in metrics.observations
        if observation.kind == "counter" and observation.name == name
    )


@dc.dataclass(frozen=True, slots=True)
class _GatedCase:
    """Expected outcome for one evaluator configuration."""

    evaluators: tuple[object, ...]
    expected_qa: QaStatus
    expected_kinds: tuple[str, ...]


_PASSED_KINDS = (
    "run.started",
    "draft.generated",
    "qa.evaluation_started",
    "qa.result",
    "tei.persisted",
    "run.succeeded",
)
_ESCALATED_KINDS = (
    "run.started",
    "draft.generated",
    "qa.evaluation_started",
    "qa.result",
    "qa.escalated",
    "run.failed",
)
_GATED_CASES: dict[str, _GatedCase] = {
    "passed": _GatedCase((passing_evaluator(),), QaStatus.PASSED, _PASSED_KINDS),
    "failed": _GatedCase((failing_evaluator(),), QaStatus.FAILED, _ESCALATED_KINDS),
    "inconclusive": _GatedCase(
        (inconclusive_evaluator(),), QaStatus.FAILED, _ESCALATED_KINDS
    ),
    "evaluator-error": _GatedCase(
        (raising_evaluator(),), QaStatus.FAILED, _ESCALATED_KINDS
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case_name", tuple(_GATED_CASES))
async def test_qa_gated_run_outcomes(
    session_factory: async_sessionmaker[AsyncSession],
    case_name: str,
) -> None:
    """Each verdict records its terminal, QA status, events, and costs."""
    case = _GATED_CASES[case_name]
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    cost_recorder = RecordingCostRecorder()
    metrics = RecordingMetrics()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        cost_recorder,
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet(
                typ.cast("tuple[typ.Any, ...]", case.evaluators),
                evaluator_timeout_seconds=0.2,
            )
        ),
    )
    run_launcher.metrics = metrics

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    run, events, _revision = await _load(session_factory, run_id)
    kinds = tuple(kind for kind, _payload in events)
    assert run.qa_status is case.expected_qa, f"qa_status={run.qa_status!r}"
    assert kinds == case.expected_kinds, f"events={kinds}"
    assert cost_recorder.provider_calls, "the draft's inference cost must be recorded"
    assert _counter_sum(metrics, _METRIC_GATE) == 1, metrics.observations
    if case.expected_qa is not QaStatus.PASSED:
        assert _counter_sum(metrics, _METRIC_DRAFT_ERRORS) == 0, (
            "QA rejection must not count as a draft error"
        )


@pytest.mark.asyncio
async def test_qa_gated_run_without_evaluators_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A gated run on an unevaluable deployment records ``qa.unavailable``."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    metrics = RecordingMetrics()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
    )
    run_launcher.metrics = metrics

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    run, events, revision = await _load(session_factory, run_id)
    kinds = [kind for kind, _payload in events]
    assert run.status is GenerationRunStatus.FAILED, f"status={run.status!r}"
    assert run.error_category == "qa.unavailable", run.error_category
    assert run.qa_status is QaStatus.PENDING, "an unevaluated run stays pending"
    assert kinds == ["run.failed"], kinds
    assert revision == 1, "no TEI may be written"


@pytest.mark.asyncio
async def test_qa_gated_generator_failure_keeps_pending_qa(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A generator failure before evaluation leaves QA pending."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = launcher(
        session_factory,
        FailingDraftGenerator(DraftScriptTransientProviderError("try later")),
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet((passing_evaluator(),))
        ),
    )

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    run, events, _revision = await _load(session_factory, run_id)
    kinds = [kind for kind, _payload in events]
    assert run.error_category == "provider.transient", run.error_category
    assert run.qa_status is QaStatus.PENDING, run.qa_status
    assert kinds == ["run.started", "run.failed"], kinds


@pytest.mark.asyncio
async def test_no_qa_run_records_no_qa_events_or_gate_metrics(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A no-QA run on an evaluating deployment keeps its direct route."""
    run_id, _ = await prepare_pending_run(session_factory)
    metrics = RecordingMetrics()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet((failing_evaluator(),))
        ),
    )
    run_launcher.metrics = metrics

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    run, events, _revision = await _load(session_factory, run_id)
    kinds = [kind for kind, _payload in events]
    assert run.qa_status is QaStatus.SKIPPED, run.qa_status
    assert "qa.evaluation_started" not in kinds, kinds
    assert _counter_sum(metrics, _METRIC_GATE) == 0, metrics.observations


@pytest.mark.asyncio
async def test_event_appends_run_in_the_run_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every append happens on the run's own launcher task."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet((passing_evaluator(),))
        ),
    )
    run_launcher.uow_factory = lambda: TaskNameAssertingUnitOfWork(session_factory)
    tracer = RecordingTracer()
    run_launcher.tracer = tracer

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    run, events, _revision = await _load(session_factory, run_id)
    print("FAILMSG", run.error_category, run.error_message)
    print("EVENTS", [kind for kind, payload in events], events)
    attributes = next(
        span.attributes
        for span in tracer.spans
        if span.name == "generation_run.execute"
    )
    assert attributes["outcome"] == "completed", attributes
    assert attributes["quality_branch"] == "qa_gated", attributes
    assert attributes["terminal"] == "qa_passed_draft_persisted", attributes

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await assert_off_task_append_is_rejected(uow.generation_runs, run_id)


@pytest.mark.asyncio
async def test_cancel_while_evaluator_awaits_stays_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancellation during evaluation fails the run without persisting TEI."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    evaluator = BlockingQualityEvaluator()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet(
                (evaluator,), evaluator_timeout_seconds=30.0
            )
        ),
    )

    await run_launcher.launch(run_id)
    await asyncio.wait_for(evaluator.started.wait(), timeout=5)
    await run_launcher.shutdown()

    run, events, revision = await _load(session_factory, run_id)
    kinds = [kind for kind, _payload in events]
    assert kinds.count("run.failed") == 1, kinds
    assert run.error_category == "launcher.shutdown", run.error_category
    assert run.qa_status is QaStatus.PENDING, run.qa_status
    assert "tei.persisted" not in kinds, kinds
    assert revision == 1, "the episode TEI must not change"


@pytest.mark.asyncio
async def test_metrics_record_evaluator_error_separately(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An evaluator error increments its own counter, not only the gate total."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    metrics = RecordingMetrics()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet((raising_evaluator("pedante"),))
        ),
    )
    run_launcher.metrics = metrics

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    labels = [
        observation.labels
        for observation in metrics.observations
        if observation.name == _METRIC_EVALUATOR_ERRORS
    ]
    assert labels == [{"evaluator": "pedante"}], labels
