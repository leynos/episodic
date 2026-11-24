"""Cancellation of a claim or a cancellation write (INV-9, INV-10).

A cancellation must not be lost, must not be duplicated, and must not hold
shutdown open: the write is shielded, its waits are bounded, and an
unverified claim is never adopted. These tests exercise the claim task,
the scheduler, and a stalled reconciliation.
"""

import asyncio
import contextlib
import dataclasses as dc
import types
import typing as typ

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.generation.launcher_support import ClaimToken, RunClaim
from tests.generation_run_launcher_read_fault_support import (
    CommitFault,
    CommitFaultUnitOfWork,
)
from tests.generation_run_launcher_support import (
    LauncherOptions,
    RecordingDraftGenerator,
    draft_result,
    launcher,
    valid_tei,
)
from tests.generation_run_quality_support import prepare_pending_qa_gated_run
from tests.test_generation_run_launcher_claim_authority import _launcher, _load

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.generation.launcher_claim import GenerationRunClaimer


@pytest.mark.asyncio
async def test_shutdown_waits_for_a_cancelled_cancellation_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A second cancellation must not let shutdown return before the write."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    fault = CommitFault()
    run_launcher = dc.replace(
        launcher(
            session_factory,
            RecordingDraftGenerator(draft_result(valid_tei())),
            options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
        ),
        uow_factory=lambda: CommitFaultUnitOfWork(session_factory, fault),
    )
    claim = RunClaim()
    await run_launcher._components()[0].claim(run_id, claim)

    fault.block = True
    write_task = asyncio.create_task(
        run_launcher._scheduler.record_cancellation_owned(run_id, claim),
    )
    await asyncio.wait_for(fault.started.wait(), timeout=5)
    write_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await write_task

    shutdown_task = asyncio.create_task(run_launcher.shutdown())
    await asyncio.sleep(0.05)
    assert not shutdown_task.done(), "shutdown must wait for the write"

    fault.release.set()
    await asyncio.wait_for(shutdown_task, timeout=5)
    run, kinds = await _load(session_factory, run_id)
    assert kinds.count("run.failed") == 1, kinds
    assert run.status is GenerationRunStatus.FAILED, run.status


@pytest.mark.asyncio
async def test_blocked_reconciliation_then_second_cancellation(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling the task during blocked reconciliation still records once."""
    from episodic.generation.launcher_claim import GenerationRunClaimer

    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = _launcher(session_factory)
    claim = RunClaim()
    await run_launcher._components()[0].claim(run_id, claim)
    claim.token = None

    original = GenerationRunClaimer.reconcile
    gate = asyncio.Event()
    release = asyncio.Event()

    async def blocked_reconcile(
        self: GenerationRunClaimer,
        run_id: uuid.UUID,
        candidate: RunClaim,
    ) -> ClaimToken | None:
        """Block reconciliation until the test releases it."""
        gate.set()
        await release.wait()
        return await original(self, run_id, candidate)

    monkeypatch.setattr(
        GenerationRunClaimer,
        "reconcile",
        blocked_reconcile,
    )

    first = asyncio.create_task(
        run_launcher._scheduler.record_cancellation_owned(run_id, claim),
    )
    await asyncio.wait_for(gate.wait(), timeout=5)
    # Cancel the task that started the shielded write, then issue a second
    # cancellation while the write is still blocked in reconciliation.
    first.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await first
    await run_launcher._scheduler.record_cancellation_owned(run_id, claim)

    release.set()
    await asyncio.wait_for(run_launcher._scheduler.drain(), timeout=5)

    run, kinds = await _load(session_factory, run_id)
    assert kinds.count("run.failed") == 1, kinds
    assert run.status is GenerationRunStatus.FAILED, run.status
    assert claim.token is not None, claim


@pytest.mark.asyncio
async def test_claim_task_cancellation_recovers_its_claim(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling the claim task during shielded reconciliation keeps authority."""
    from episodic.generation.launcher_claim import GenerationRunClaimer

    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    fault = CommitFault(lose_ack=True)
    run_launcher = dc.replace(
        launcher(
            session_factory,
            RecordingDraftGenerator(draft_result(valid_tei())),
            options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
        ),
        uow_factory=lambda: CommitFaultUnitOfWork(session_factory, fault),
    )
    claim = RunClaim()
    control = types.SimpleNamespace(
        gate=asyncio.Event(),
        release=asyncio.Event(),
        settled=asyncio.Event(),
        is_first_call=True,
    )

    async def blocked_reconcile(
        self: GenerationRunClaimer,
        run_id: uuid.UUID,
        candidate: RunClaim,
        original: cabc.Callable[
            ..., cabc.Awaitable[ClaimToken | None]
        ] = GenerationRunClaimer.reconcile,
    ) -> ClaimToken | None:
        """Block the first reconciliation until the test releases it."""
        if control.is_first_call:
            control.is_first_call = False
            control.gate.set()
            await control.release.wait()
        outcome = await original(self, run_id, candidate)
        control.settled.set()
        return outcome

    monkeypatch.setattr(
        GenerationRunClaimer,
        "reconcile",
        blocked_reconcile,
    )

    claim_task = asyncio.create_task(
        run_launcher._components()[0].claim(run_id, claim),
    )
    await asyncio.wait_for(control.gate.wait(), timeout=5)
    # The commit raised CancelledError, so the claim task is inside the
    # shielded reconciliation. Cancel the claim task itself a second time.
    claim_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await claim_task
    assert claim_task.cancelled(), "the claim task must observe the cancellation"

    control.release.set()
    await asyncio.wait_for(control.settled.wait(), timeout=5)
    assert claim.token is not None, "the shielded reconcile must restore authority"

    await run_launcher._scheduler.record_cancellation_owned(run_id, claim)
    await asyncio.wait_for(run_launcher._scheduler.drain(), timeout=5)

    run, kinds = await _load(session_factory, run_id)
    assert kinds == ["run.started", "run.failed"], kinds
    assert run.status is GenerationRunStatus.FAILED, run.status
    assert run.error_category == "launcher.shutdown", run.error_category
    assert not run_launcher._scheduler._tasks, "scheduled tasks must be drained"
    assert not run_launcher._scheduler._cancellation_tasks, "writes must be drained"


@pytest.mark.asyncio
async def test_stalled_reconciliation_is_bounded(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled reconciliation cannot hold a cancelled claim open."""
    from episodic.generation.launcher_claim import GenerationRunClaimer

    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    fault = CommitFault(lose_ack=True)
    run_launcher = dc.replace(
        launcher(
            session_factory,
            RecordingDraftGenerator(draft_result(valid_tei())),
            options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
        ),
        uow_factory=lambda: CommitFaultUnitOfWork(session_factory, fault),
        cancellation_write_timeout_seconds=0.2,
    )
    claimer = run_launcher._components()[0]
    entered = asyncio.Event()

    async def stalled_reconcile(
        self: GenerationRunClaimer,
        run_id: uuid.UUID,
        candidate: RunClaim,
    ) -> ClaimToken | None:
        """Block reconciliation forever, recording that it was entered."""
        _ = (self, run_id, candidate)
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError

    monkeypatch.setattr(GenerationRunClaimer, "reconcile", stalled_reconcile)

    claim = RunClaim()
    claim_task = asyncio.create_task(claimer.claim(run_id, claim))
    await asyncio.wait_for(entered.wait(), timeout=5)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(claim_task, timeout=5)
    assert claim_task.done(), "the bounded wait must release the claim task"
    assert claim.token is None, "an unverified claim must not be adopted"


@pytest.mark.asyncio
async def test_a_timed_out_cancellation_leaves_the_run_claimable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A cancelled write that never lands leaves a pending run for the next claim."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = dc.replace(
        launcher(
            session_factory,
            RecordingDraftGenerator(draft_result(valid_tei())),
            options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
        ),
        cancellation_write_timeout_seconds=0.2,
    )
    stalled = asyncio.Event()

    async def never_writes(run_id: uuid.UUID, claim: RunClaim) -> bool:
        """Never finish the write, recording that it was called."""
        _ = (run_id, claim)
        await stalled.wait()
        return False

    run_launcher._scheduler.record_cancellation = never_writes
    await asyncio.wait_for(
        run_launcher._scheduler.record_cancellation_owned(run_id, RunClaim()),
        timeout=5,
    )

    run, kinds = await _load(session_factory, run_id)
    assert run.status is GenerationRunStatus.PENDING, kinds
    assert run.started_at is None, "an unlanded claim must not start the run"

    fresh = _launcher(session_factory)
    won = await fresh._components()[0].claim(run_id, RunClaim())
    assert won is not None, "the next launcher must be able to claim the run"
