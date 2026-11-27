"""Shutdown-safety tests for QA-gated terminals (INV-10).

A gated run can be cancelled while an evaluator awaits, inside the passing
terminal transaction, or inside the escalation transaction. In every case the
uncommitted terminal must roll back and exactly one ``launcher.shutdown``
failure must be recorded, leaving QA pending and the episode TEI unchanged.
"""

import asyncio
import typing as typ

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.generation_run_launcher_support import (
    LauncherOptions,
    RecordingDraftGenerator,
    draft_result,
    launcher,
    valid_tei,
)
from tests.generation_run_quality_support import (
    BlockingCostRecorder,
    BlockingQualityEvaluator,
    failing_evaluator,
    passing_evaluator,
    prepare_pending_qa_gated_run,
)

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.generation.launcher import InProcessGenerationRunLauncher


async def _cancel_at(
    run_launcher: InProcessGenerationRunLauncher,
    started: asyncio.Event,
) -> None:
    """Wait for a blocking fake to report entry, then shut the launcher down.

    The shutdown is unconditional: if the entry wait times out, the launched
    run must not be left blocked for a later test.
    """
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
    finally:
        await run_launcher.shutdown()


async def _assert_shutdown_state(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> None:
    """Assert the uncommitted terminal rolled back and shutdown was recorded once."""
    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)
    assert run is not None, f"run {run_id} was not persisted"
    async with SqlAlchemyUnitOfWork(factory) as uow:
        episode = await uow.episodes.get(run.episode_id)
    assert episode is not None, f"episode for run {run_id} was not persisted"
    episode_revision = episode.tei_revision
    kinds = [event.kind for event in events]

    assert run.status is GenerationRunStatus.FAILED, f"status={run.status!r}"
    assert run.error_category == "launcher.shutdown", run.error_category
    assert run.qa_status is QaStatus.PENDING, f"qa_status={run.qa_status!r}"
    assert kinds.count("run.failed") == 1, kinds
    assert "tei.persisted" not in kinds, kinds
    assert episode_revision == 1, f"TEI revision changed to {episode_revision}"


@pytest.mark.asyncio
async def test_cancel_while_evaluator_awaits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancellation during evaluation leaves QA pending and writes no TEI."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    evaluator = BlockingQualityEvaluator()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet(
                (evaluator,),
                evaluator_timeout_seconds=30.0,
            )
        ),
    )

    await run_launcher.launch(run_id)
    await _cancel_at(run_launcher, evaluator.started)

    await _assert_shutdown_state(session_factory, run_id)


@pytest.mark.asyncio
async def test_cancel_inside_passing_terminal_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancellation inside the pass transaction rolls the whole terminal back."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    recorder = BlockingCostRecorder()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        typ.cast("typ.Any", recorder),
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet((passing_evaluator(),))
        ),
    )

    await run_launcher.launch(run_id)
    await _cancel_at(run_launcher, recorder.started)

    await _assert_shutdown_state(session_factory, run_id)


@pytest.mark.asyncio
async def test_cancel_inside_escalation_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancellation inside the escalation transaction rolls its events back."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    recorder = BlockingCostRecorder()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        typ.cast("typ.Any", recorder),
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet((failing_evaluator(),))
        ),
    )

    await run_launcher.launch(run_id)
    await _cancel_at(run_launcher, recorder.started)

    await _assert_shutdown_state(session_factory, run_id)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        events = await uow.generation_runs.list_events(run_id)
    assert "qa.escalated" not in [event.kind for event in events], (
        "the uncommitted escalation events must roll back"
    )
