"""INV-9 matrix: one writer per run, with ordered publication.

Every valid quality-mode and outcome cell named by the plan runs through the
real launcher against py-pglite. For each cell the test asserts that the event
sequence is strictly increasing, that exactly one terminal event is written
last, that every append runs in a task named for the run, and that the cell's
QA status, failure category, costs, and draft-error metric are correct.
"""

import asyncio
import dataclasses as dc
import typing as typ

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.draft_script import DraftScriptTransientProviderError
from tests.generation_run_launcher_observation_support import RecordingMetrics
from tests.generation_run_launcher_support import (
    BlockingDraftGenerator,
    FailingDraftGenerator,
    LauncherOptions,
    RecordingCostRecorder,
    RecordingDraftGenerator,
    draft_result,
    launcher,
    prepare_pending_run,
    valid_tei,
)
from tests.generation_run_quality_support import (
    BlockingQualityEvaluator,
    TaskNameAssertingUnitOfWork,
    failing_evaluator,
    inconclusive_evaluator,
    passing_evaluator,
    prepare_pending_qa_gated_run,
    raising_evaluator,
)

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.generation.draft_script import DraftScriptGenerator
    from episodic.generation.launcher import InProcessGenerationRunLauncher

_TERMINAL_KINDS = frozenset({"run.succeeded", "run.failed"})
_METRIC_DRAFT_ERRORS = "generation_run_draft_errors_total"
_METRIC_EVALUATOR_ERRORS = "generation_run_qa_evaluator_errors_total"

_DRAFT = "draft"
_FAILING = "failing"
_BLOCKING = "blocking"


@dc.dataclass(frozen=True, slots=True)
class _Cell:
    """Expected contract for one mode and outcome combination."""

    mode: QualityMode
    generator: str
    evaluators: tuple[object, ...]
    cancel_on: str | None
    expected_terminal: str
    expected_qa: QaStatus
    expected_category: str | None
    expects_costs: bool
    expected_draft_errors: int
    expected_evaluator_errors: int


_MATRIX: dict[str, _Cell] = {
    "no-qa-succeeded": _Cell(
        mode=QualityMode.DRAFT_WITHOUT_QA,
        generator=_DRAFT,
        evaluators=(),
        cancel_on=None,
        expected_terminal="run.succeeded",
        expected_qa=QaStatus.SKIPPED,
        expected_category=None,
        expects_costs=True,
        expected_draft_errors=0,
        expected_evaluator_errors=0,
    ),
    "no-qa-generator-failure": _Cell(
        mode=QualityMode.DRAFT_WITHOUT_QA,
        generator=_FAILING,
        evaluators=(),
        cancel_on=None,
        expected_terminal="run.failed",
        expected_qa=QaStatus.SKIPPED,
        expected_category="provider.transient",
        expects_costs=False,
        expected_draft_errors=1,
        expected_evaluator_errors=0,
    ),
    "no-qa-cancelled": _Cell(
        mode=QualityMode.DRAFT_WITHOUT_QA,
        generator=_BLOCKING,
        evaluators=(),
        cancel_on="generator",
        expected_terminal="run.failed",
        expected_qa=QaStatus.SKIPPED,
        expected_category="launcher.shutdown",
        expects_costs=False,
        expected_draft_errors=1,
        expected_evaluator_errors=0,
    ),
    "gated-passed": _Cell(
        mode=QualityMode.QA_GATED,
        generator=_DRAFT,
        evaluators=(passing_evaluator(),),
        cancel_on=None,
        expected_terminal="run.succeeded",
        expected_qa=QaStatus.PASSED,
        expected_category=None,
        expects_costs=True,
        expected_draft_errors=0,
        expected_evaluator_errors=0,
    ),
    "gated-escalated-failed": _Cell(
        mode=QualityMode.QA_GATED,
        generator=_DRAFT,
        evaluators=(failing_evaluator(),),
        cancel_on=None,
        expected_terminal="run.failed",
        expected_qa=QaStatus.FAILED,
        expected_category="qa.escalation_required",
        expects_costs=True,
        expected_draft_errors=0,
        expected_evaluator_errors=0,
    ),
    "gated-escalated-inconclusive": _Cell(
        mode=QualityMode.QA_GATED,
        generator=_DRAFT,
        evaluators=(inconclusive_evaluator(),),
        cancel_on=None,
        expected_terminal="run.failed",
        expected_qa=QaStatus.FAILED,
        expected_category="qa.escalation_required",
        expects_costs=True,
        expected_draft_errors=0,
        expected_evaluator_errors=0,
    ),
    "gated-evaluator-error": _Cell(
        mode=QualityMode.QA_GATED,
        generator=_DRAFT,
        evaluators=(raising_evaluator(),),
        cancel_on=None,
        expected_terminal="run.failed",
        expected_qa=QaStatus.FAILED,
        expected_category="qa.escalation_required",
        expects_costs=True,
        expected_draft_errors=0,
        expected_evaluator_errors=1,
    ),
    "gated-unavailable": _Cell(
        mode=QualityMode.QA_GATED,
        generator=_DRAFT,
        evaluators=(),
        cancel_on=None,
        expected_terminal="run.failed",
        expected_qa=QaStatus.PENDING,
        expected_category="qa.unavailable",
        expects_costs=False,
        expected_draft_errors=1,
        expected_evaluator_errors=0,
    ),
    "gated-generator-failure": _Cell(
        mode=QualityMode.QA_GATED,
        generator=_FAILING,
        evaluators=(passing_evaluator(),),
        cancel_on=None,
        expected_terminal="run.failed",
        expected_qa=QaStatus.PENDING,
        expected_category="provider.transient",
        expects_costs=False,
        expected_draft_errors=1,
        expected_evaluator_errors=0,
    ),
    "gated-cancelled": _Cell(
        mode=QualityMode.QA_GATED,
        generator=_DRAFT,
        evaluators=(BlockingQualityEvaluator(),),
        cancel_on="evaluator",
        expected_terminal="run.failed",
        expected_qa=QaStatus.PENDING,
        expected_category="launcher.shutdown",
        expects_costs=False,
        expected_draft_errors=1,
        expected_evaluator_errors=0,
    ),
}


def _generator(cell: _Cell) -> DraftScriptGenerator:
    """Build the generator the cell calls for."""
    if cell.generator == _FAILING:
        return FailingDraftGenerator(
            DraftScriptTransientProviderError("provider fault")
        )
    if cell.generator == _BLOCKING:
        return BlockingDraftGenerator()
    return RecordingDraftGenerator(draft_result(valid_tei()))


def _launcher_for(
    session_factory: async_sessionmaker[AsyncSession],
    cell: _Cell,
    cost_recorder: RecordingCostRecorder,
) -> InProcessGenerationRunLauncher:
    """Build a launcher whose every append asserts the run's task name."""
    evaluators = typ.cast("tuple[typ.Any, ...]", cell.evaluators)
    run_launcher = launcher(
        session_factory,
        _generator(cell),
        cost_recorder,
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet(
                evaluators,
                evaluator_timeout_seconds=1.0,
            )
        ),
    )
    return dc.replace(
        run_launcher,
        uow_factory=lambda: TaskNameAssertingUnitOfWork(session_factory),
    )


async def _prepare(
    session_factory: async_sessionmaker[AsyncSession],
    cell: _Cell,
) -> uuid.UUID:
    """Persist a pending run for the cell's mode."""
    if cell.mode is QualityMode.QA_GATED:
        run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    else:
        run_id, _ = await prepare_pending_run(session_factory)
    return run_id


async def _wait_until_blocked(
    run_launcher: InProcessGenerationRunLauncher,
    cell: _Cell,
) -> None:
    """Wait for the cell's designated blocking point before shutdown."""
    if cell.cancel_on == "generator":
        generator = typ.cast("BlockingDraftGenerator", run_launcher.draft_generator)
        await asyncio.wait_for(generator.started.wait(), timeout=5)
        return
    evaluator = typ.cast("BlockingQualityEvaluator", cell.evaluators[0])
    await asyncio.wait_for(evaluator.started.wait(), timeout=5)


async def _load_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> tuple[GenerationRun, list[tuple[int, str]]]:
    """Load a run and its ordered ``(seq, kind)`` stream."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)
    assert run is not None, f"run {run_id} was not persisted"
    return run, [(event.seq, event.kind) for event in events]


def _counter_sum(metrics: RecordingMetrics, name: str) -> int:
    """Count matching counter observations."""
    return sum(
        1
        for observation in metrics.observations
        if observation.kind == "counter" and observation.name == name
    )


def _assert_ordered_publication(
    events: list[tuple[int, str]],
    cell: _Cell,
) -> None:
    """Assert strictly increasing seq and one terminal event, written last."""
    seqs = [seq for seq, _ in events]
    assert seqs == sorted(set(seqs)), f"seq must strictly increase: {seqs}"
    kinds = [kind for _, kind in events]
    terminals = [kind for kind in kinds if kind in _TERMINAL_KINDS]
    assert terminals == [cell.expected_terminal], f"terminals={terminals}, {kinds}"
    assert kinds[-1] == cell.expected_terminal, f"terminal must be last: {kinds}"


@pytest.mark.asyncio
@pytest.mark.parametrize("cell_name", tuple(_MATRIX))
async def test_inv9_cell(
    session_factory: async_sessionmaker[AsyncSession],
    cell_name: str,
) -> None:
    """Every mode and outcome cell satisfies the single-writer contract."""
    cell = _MATRIX[cell_name]
    run_id = await _prepare(session_factory, cell)
    cost_recorder = RecordingCostRecorder()
    metrics = RecordingMetrics()
    run_launcher = _launcher_for(session_factory, cell, cost_recorder)
    run_launcher.metrics = metrics

    await run_launcher.launch(run_id)
    if cell.cancel_on is not None:
        await _wait_until_blocked(run_launcher, cell)
        await run_launcher.shutdown()
    else:
        await run_launcher.drain()

    run, events = await _load_events(session_factory, run_id)
    _assert_ordered_publication(events, cell)
    expected_status = (
        GenerationRunStatus.SUCCEEDED
        if cell.expected_terminal == "run.succeeded"
        else GenerationRunStatus.FAILED
    )
    assert run.status is expected_status, f"status={run.status!r}, {events}"
    assert run.qa_status is cell.expected_qa, f"qa_status={run.qa_status!r}"
    if cell.expected_category is not None:
        assert run.error_category == cell.expected_category, run.error_category
    if cell.expects_costs:
        assert cost_recorder.provider_calls, "the consumed draft must cost a call"
    else:
        assert not cost_recorder.provider_calls, "no draft may be charged"
    assert _counter_sum(metrics, _METRIC_DRAFT_ERRORS) == (
        cell.expected_draft_errors
    ), metrics.observations
    assert _counter_sum(metrics, _METRIC_EVALUATOR_ERRORS) == (
        cell.expected_evaluator_errors
    ), metrics.observations
