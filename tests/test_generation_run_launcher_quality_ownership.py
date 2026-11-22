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
from episodic.generation.launcher_support import Failure, RunOwnership
from tests.generation_run_launcher_read_fault_support import (
    CancelCommitFault,
    CancelCommitUnitOfWork,
    ClaimExitFault,
    ClaimExitFaultUnitOfWork,
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
    import collections.abc as cabc
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
@pytest.mark.parametrize(
    ("make_fault", "blocks"),
    [(ReadFault, False), (blocking_read_fault, True)],
    ids=["read-fault", "shutdown-before-claim"],
)
async def test_losing_launcher_cannot_fail_the_run(
    session_factory: async_sessionmaker[AsyncSession],
    make_fault: cabc.Callable[[], ReadFault],
    *,
    blocks: bool,
) -> None:
    """A read fault or a pre-claim shutdown must not fail another's run."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    generator = ReleasableDraftGenerator(draft_result(valid_tei()))
    owner = _owner_launcher(session_factory, generator)
    fault = make_fault()
    loser = _loser_launcher(session_factory, fault)

    await owner.launch(run_id)
    await asyncio.wait_for(generator.started.wait(), timeout=5)
    await loser.launch(run_id)
    if blocks:
        await asyncio.wait_for(fault.started.wait(), timeout=5)
        await loser.shutdown()
    else:
        await loser.drain()

    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.RUNNING, kinds
    assert "run.failed" not in kinds, kinds

    generator.release.set()
    fault.release.set()
    await owner.drain()
    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.SUCCEEDED, kinds


@pytest.mark.asyncio
async def test_refused_cancellation_does_not_suppress_the_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A refused cancellation must not mark the run cancelled for its owner.

    The losing invocation finishes first here, which is the interleaving a
    name-based or unconditional dedup would get wrong: its write is refused,
    and if that refusal still recorded the run as cancelled, the owner's
    shutdown write would be skipped and the run would stay running.
    """
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    generator = ReleasableDraftGenerator(draft_result(valid_tei()))
    run_launcher = _owner_launcher(session_factory, generator)

    await run_launcher.launch(run_id)
    await asyncio.wait_for(generator.started.wait(), timeout=5)
    await run_launcher._record_cancellation_owned(run_id, RunOwnership())
    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.RUNNING, kinds
    assert "run.failed" not in kinds, kinds

    await run_launcher.shutdown()
    run, kinds = await _load(session_factory, run_id)
    assert kinds.count("run.failed") == 1, kinds
    assert run.status is GenerationRunStatus.FAILED, kinds
    assert run.error_category == "launcher.shutdown", run.error_category


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "category", "message"),
    [
        ("error", "unexpected", "session close fault"),
        ("cancel", "launcher.shutdown", "cancelled during shutdown."),
    ],
    ids=["close-error", "cancelled-close"],
)
async def test_claim_exit_fault_still_records_the_failure(
    session_factory: async_sessionmaker[AsyncSession],
    mode: str,
    category: str,
    message: str,
) -> None:
    """A close fault or cancellation after the claim commits must still fail."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    fault = ClaimExitFault(mode=mode)
    run_launcher = dc.replace(
        launcher(
            session_factory,
            RecordingDraftGenerator(draft_result(valid_tei())),
            options=LauncherOptions(
                evaluator_set=QualityEvaluatorSet(
                    (passing_evaluator(),),
                    evaluator_timeout_seconds=5.0,
                )
            ),
        ),
        uow_factory=lambda: ClaimExitFaultUnitOfWork(session_factory, fault),
    )

    await run_launcher.launch(run_id)
    if mode == "cancel":
        await asyncio.wait_for(fault.closing.wait(), timeout=5)
        await run_launcher.shutdown()
        fault.release.set()
    else:
        await run_launcher.drain()

    run, kinds = await _load(session_factory, run_id)
    assert fault.failed, "the exit fault must have fired"
    assert run.status is GenerationRunStatus.FAILED, kinds
    assert run.error_category == category, run.error_category
    assert message in (run.error_message or ""), run.error_message
    assert kinds == ["run.started", "run.failed"], kinds


@pytest.mark.asyncio
async def test_rolled_back_failure_claim_is_not_reused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A cancelled failure write must not leave a stale ownership flag."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    fault = CancelCommitFault()
    flaky = dc.replace(
        launcher(
            session_factory,
            RecordingDraftGenerator(draft_result(valid_tei())),
            options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
        ),
        uow_factory=lambda: CancelCommitUnitOfWork(session_factory, fault),
    )
    ownership = RunOwnership()

    with pytest.raises(asyncio.CancelledError):
        await flaky._record_failure(
            run_id,
            Failure("transient failure", "unexpected"),
            ownership=ownership,
        )
    assert not ownership.claimed, "a rolled-back claim must not be retained"

    generator = ReleasableDraftGenerator(draft_result(valid_tei()))
    owner = _owner_launcher(session_factory, generator)
    await owner.launch(run_id)
    await asyncio.wait_for(generator.started.wait(), timeout=5)

    await flaky._record_cancellation_owned(run_id, ownership)
    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.RUNNING, kinds
    assert "run.failed" not in kinds, kinds

    generator.release.set()
    await owner.drain()
    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.SUCCEEDED, kinds
