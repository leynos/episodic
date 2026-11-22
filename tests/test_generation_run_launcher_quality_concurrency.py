"""Concurrency boundaries for QA-gated launcher runs (INV-9, D16).

These tests cover the failures CodeRabbit's completeness assessment raised:
a losing launcher must not fail a run another task claimed, cancelling one
graph invocation must not touch another invocation's node tasks, and a failed
quality-mode read must still record a terminal failure.
"""

import asyncio
import contextlib
import dataclasses as dc
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import (
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_graph_ports import (
    ContentGenerationRequest,
    QualityEvaluatorSet,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.observability import RecordingTracer
from episodic.orchestration import LangGraphContentGenerationGraph
from tests._content_graph_fakes import RecordingSteps
from tests.generation_run_launcher_read_fault_support import (
    ReadFault,
    RunReadFaultUnitOfWork,
)
from tests.generation_run_launcher_support import (
    BlockingDraftGenerator,
    LauncherOptions,
    RecordingDraftGenerator,
    ReleasableDraftGenerator,
    draft_result,
    launcher,
    prepare_pending_run,
    valid_tei,
)
from tests.generation_run_quality_support import (
    BlockingQualityEvaluator,
    ReleasableQualityEvaluator,
    TaskNameAssertingUnitOfWork,
    assert_off_task_append_is_rejected,
    failing_evaluator,
    passing_evaluator,
    prepare_pending_qa_gated_run,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.generation_graph_ports import QualityEvaluatorPort
    from episodic.generation.launcher import InProcessGenerationRunLauncher


async def _load(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> tuple[GenerationRun, list[str]]:
    """Load a run and its event kinds."""
    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)
    assert run is not None, f"run {run_id} was not persisted"
    return run, [event.kind for event in events]


@pytest.mark.asyncio
async def test_losing_launcher_cannot_fail_a_claimed_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A launcher with no evaluators must not fail another task's claimed run."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    generator = ReleasableDraftGenerator(draft_result(valid_tei()))
    owner = launcher(
        session_factory,
        generator,
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet(
                (passing_evaluator(),),
                evaluator_timeout_seconds=5.0,
            )
        ),
    )
    loser_tracer = RecordingTracer()
    loser = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
    )
    loser.tracer = loser_tracer

    await owner.launch(run_id)
    await asyncio.wait_for(generator.started.wait(), timeout=5)
    await loser.launch(run_id)
    await loser.drain()

    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.RUNNING, (
        f"the losing launcher changed status to {run.status!r}: {kinds}"
    )
    assert "run.failed" not in kinds, kinds
    assert loser_tracer.spans[0].attributes["outcome"] == "not_claimed", (
        loser_tracer.spans[0].attributes
    )

    generator.release.set()
    await owner.drain()
    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.SUCCEEDED, kinds
    assert run.qa_status is QaStatus.PASSED, run.qa_status


@pytest.mark.asyncio
async def test_cancelling_one_runner_preserves_another_run_task() -> None:
    """Cancelling one graph invocation must not cancel another's node tasks."""
    request = ContentGenerationRequest(
        run_id=uuid.uuid4(),
        quality_mode=QualityMode.QA_GATED,
    )
    blocking = BlockingQualityEvaluator()
    releasable = ReleasableQualityEvaluator()
    first = LangGraphContentGenerationGraph(
        QualityEvaluatorSet((blocking,), evaluator_timeout_seconds=30.0)
    )
    second = LangGraphContentGenerationGraph(
        QualityEvaluatorSet((releasable,), evaluator_timeout_seconds=5.0)
    )
    first_steps = RecordingSteps()
    second_steps = RecordingSteps()
    first_task = asyncio.create_task(
        first.run(request, steps=first_steps),
        name="runner-first",
    )
    second_task = asyncio.create_task(
        second.run(request, steps=second_steps),
        name="runner-second",
    )
    try:
        await asyncio.wait_for(blocking.started.wait(), timeout=5)
        await asyncio.wait_for(releasable.started.wait(), timeout=5)
        first_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await first_task
        releasable.release.set()
        terminal = await asyncio.wait_for(second_task, timeout=5)
    finally:
        releasable.release.set()
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    assert terminal.value == "qa_passed_draft_persisted", terminal
    assert "complete_with_draft" in second_steps.step_names(), second_steps.step_names()


@pytest.mark.asyncio
async def test_failed_quality_mode_read_records_a_terminal_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A failed initial read must still record a terminal failure."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    fault = ReadFault()
    run_launcher = dc.replace(
        launcher(
            session_factory,
            RecordingDraftGenerator(draft_result(valid_tei())),
            options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
        ),
        uow_factory=lambda: RunReadFaultUnitOfWork(session_factory, fault),
    )

    await run_launcher.launch(run_id)
    await run_launcher.drain()

    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.FAILED, kinds
    assert run.error_category == "unexpected", run.error_category
    assert run.error_message == "transient read fault", run.error_message
    assert kinds == ["run.failed"], kinds


@dc.dataclass(frozen=True, slots=True)
class _TaskCase:
    """One outcome cell for the single-writer task check."""

    no_qa: bool
    evaluator: object | None
    blocks_until_shutdown: bool
    expected_terminal: str
    expected_outcome: str
    expected_branch: str | None
    expected_graph_terminal: str | None


_TASK_CASES: dict[str, _TaskCase] = {
    "gated-passed": _TaskCase(
        no_qa=False,
        evaluator=passing_evaluator(),
        blocks_until_shutdown=False,
        expected_terminal="run.succeeded",
        expected_outcome="completed",
        expected_branch="qa_gated",
        expected_graph_terminal="qa_passed_draft_persisted",
    ),
    "gated-failed": _TaskCase(
        no_qa=False,
        evaluator=failing_evaluator(),
        blocks_until_shutdown=False,
        expected_terminal="run.failed",
        expected_outcome="escalated",
        expected_branch="qa_gated",
        expected_graph_terminal="qa_escalated",
    ),
    "no-qa": _TaskCase(
        no_qa=True,
        evaluator=None,
        blocks_until_shutdown=False,
        expected_terminal="run.succeeded",
        expected_outcome="completed",
        expected_branch="draft_without_qa",
        expected_graph_terminal="draft_persisted_without_qa",
    ),
    "shutdown": _TaskCase(
        no_qa=False,
        evaluator=BlockingQualityEvaluator(),
        blocks_until_shutdown=True,
        expected_terminal="run.failed",
        expected_outcome="cancelled",
        expected_branch=None,
        expected_graph_terminal=None,
    ),
}


def _case_launcher(
    session_factory: async_sessionmaker[AsyncSession],
    case: _TaskCase,
) -> InProcessGenerationRunLauncher:
    """Build a launcher whose every append asserts the run's task name."""
    evaluators: tuple[QualityEvaluatorPort, ...] = (
        ()
        if case.evaluator is None
        else (typ.cast("QualityEvaluatorPort", case.evaluator),)
    )
    generator = (
        BlockingDraftGenerator()
        if case.blocks_until_shutdown
        else RecordingDraftGenerator(draft_result(valid_tei()))
    )
    run_launcher = launcher(
        session_factory,
        generator,
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet(
                evaluators,
                evaluator_timeout_seconds=5.0,
            )
        ),
    )
    run_launcher.uow_factory = lambda: TaskNameAssertingUnitOfWork(session_factory)
    return run_launcher


async def _run_case(
    session_factory: async_sessionmaker[AsyncSession],
    case: _TaskCase,
    run_launcher: InProcessGenerationRunLauncher,
) -> tuple[uuid.UUID, list[str], RecordingTracer]:
    """Drive one case to its terminal state and return its run and events."""
    if case.no_qa:
        run_id, _ = await prepare_pending_run(session_factory)
    else:
        run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    tracer = RecordingTracer()
    run_launcher.tracer = tracer
    await run_launcher.launch(run_id)
    if case.blocks_until_shutdown:
        generator = typ.cast("BlockingDraftGenerator", run_launcher.draft_generator)
        await asyncio.wait_for(generator.started.wait(), timeout=5)
        await run_launcher.shutdown()
    else:
        await run_launcher.drain()
    _run, kinds = await _load(session_factory, run_id)
    return run_id, kinds, tracer


@pytest.mark.asyncio
@pytest.mark.parametrize("case_name", tuple(_TASK_CASES))
async def test_every_append_uses_the_run_task(
    session_factory: async_sessionmaker[AsyncSession],
    case_name: str,
) -> None:
    """Every append, including the shutdown write, uses the run's own task."""
    case = _TASK_CASES[case_name]
    run_launcher = _case_launcher(session_factory, case)
    run_id, kinds, tracer = await _run_case(session_factory, case, run_launcher)

    terminals = [kind for kind in kinds if kind in {"run.succeeded", "run.failed"}]
    assert terminals == [case.expected_terminal], kinds
    attributes = next(
        span.attributes
        for span in tracer.spans
        if span.name == "generation_run.execute"
    )
    assert attributes["outcome"] == case.expected_outcome, attributes
    if case.expected_branch is not None:
        assert attributes["quality_branch"] == case.expected_branch, attributes
        assert attributes["terminal"] == case.expected_graph_terminal, attributes

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await assert_off_task_append_is_rejected(uow.generation_runs, run_id)
