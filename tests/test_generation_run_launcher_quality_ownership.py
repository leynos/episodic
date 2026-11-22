"""Claim ownership gates terminal writes for competing launchers (INV-9).

A task name records which invocation wrote an event; it does not prove that
invocation owns the run. These tests drive two launchers against one run and
assert that only the invocation whose atomic claim succeeded can record a
terminal state, including on the failure and cancellation paths.
"""

import asyncio
import dataclasses as dc
import typing as typ

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.generation_run_launcher_read_fault_support import (
    ReadFault,
    RunReadFaultUnitOfWork,
    blocking_read_fault,
)
from tests.generation_run_launcher_support import (
    LauncherOptions,
    RecordingDraftGenerator,
    ReleasableDraftGenerator,
    draft_result,
    launcher,
    valid_tei,
)
from tests.generation_run_quality_support import (
    passing_evaluator,
    prepare_pending_qa_gated_run,
)

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


def _owner_launcher(
    session_factory: async_sessionmaker[AsyncSession],
    generator: ReleasableDraftGenerator,
) -> InProcessGenerationRunLauncher:
    """Build a launcher that claims the run and blocks in generation."""
    return launcher(
        session_factory,
        generator,
        options=LauncherOptions(
            evaluator_set=QualityEvaluatorSet(
                (passing_evaluator(),),
                evaluator_timeout_seconds=5.0,
            )
        ),
    )


def _loser_launcher(
    session_factory: async_sessionmaker[AsyncSession],
    fault: ReadFault,
) -> InProcessGenerationRunLauncher:
    """Build a launcher whose initial run read carries the given fault."""
    return dc.replace(
        launcher(
            session_factory,
            RecordingDraftGenerator(draft_result(valid_tei())),
            options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
        ),
        uow_factory=lambda: RunReadFaultUnitOfWork(session_factory, fault),
    )


@pytest.mark.asyncio
async def test_read_fault_in_a_losing_launcher_cannot_fail_the_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A pre-claim read fault must not fail a run another launcher owns."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    generator = ReleasableDraftGenerator(draft_result(valid_tei()))
    owner = _owner_launcher(session_factory, generator)
    loser = _loser_launcher(session_factory, ReadFault())

    await owner.launch(run_id)
    await asyncio.wait_for(generator.started.wait(), timeout=5)
    await loser.launch(run_id)
    await loser.drain()

    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.RUNNING, kinds
    assert "run.failed" not in kinds, kinds

    generator.release.set()
    await owner.drain()
    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.SUCCEEDED, kinds


@pytest.mark.asyncio
async def test_shutdown_before_a_claim_cannot_fail_the_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancelling a losing launcher before it claims must not fail the run."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    generator = ReleasableDraftGenerator(draft_result(valid_tei()))
    owner = _owner_launcher(session_factory, generator)
    fault = blocking_read_fault()
    loser = _loser_launcher(session_factory, fault)

    await owner.launch(run_id)
    await asyncio.wait_for(generator.started.wait(), timeout=5)
    await loser.launch(run_id)
    await asyncio.wait_for(fault.started.wait(), timeout=5)
    await loser.shutdown()

    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.RUNNING, kinds
    assert "run.failed" not in kinds, kinds

    generator.release.set()
    fault.release.set()
    await owner.drain()
    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.SUCCEEDED, kinds
