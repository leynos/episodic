"""Claim reconciliation and failure-write transactions (INV-9).

A claim whose commit acknowledgement is lost is re-adopted only when the
durable row carries this attempt's unique proof. These tests cover that
reconciliation, the single transaction shared by a failure claim and its
write, and the cancellation ordering that depends on both.
"""

import asyncio
import contextlib
import dataclasses as dc
import types
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.generation.launcher_support import ClaimToken, Failure, RunClaim
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
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.launcher_support import FailureWrite


@pytest.mark.asyncio
async def test_lost_commit_acknowledgement_is_reconciled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A claim whose commit acknowledgement is lost keeps its authority."""
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

    with pytest.raises(asyncio.CancelledError):
        await run_launcher._claim_and_start(run_id, claim)

    assert claim.token is not None, "the durable claim must be re-adopted"
    result = await run_launcher._record_owned_failure(
        run_id,
        Failure("after lost ack", "unexpected"),
        token=claim.token,
    )
    assert result.written is True, result
    run, kinds = await _load(session_factory, run_id)
    assert kinds == ["run.started", "run.failed"], kinds
    assert run.status is GenerationRunStatus.FAILED, run.status


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
    await run_launcher._claim_and_start(run_id, claim)

    fault.block = True
    write_task = asyncio.create_task(
        run_launcher._record_cancellation_owned(run_id, claim),
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
async def test_failure_claim_and_write_share_one_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The authority claim and the failure write use the same unit of work."""
    from episodic.generation.launcher import InProcessGenerationRunLauncher

    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = _launcher(session_factory)
    seen: dict[str, object] = {}

    original_claim = InProcessGenerationRunLauncher._claim_for_failure
    original_write = InProcessGenerationRunLauncher._write_failure

    async def claim_for_failure(
        self: InProcessGenerationRunLauncher,
        uow: CanonicalUnitOfWork,
        failed_run_id: uuid.UUID,
        claim: RunClaim,
    ) -> ClaimToken | None:
        """Record the unit of work used for the claim."""
        seen["claim"] = uow
        return await original_claim(self, uow, failed_run_id, claim)

    async def write_failure(
        self: InProcessGenerationRunLauncher,
        uow: CanonicalUnitOfWork,
        write: FailureWrite,
    ) -> None:
        """Record the unit of work used for the write."""
        seen["write"] = uow
        await original_write(self, uow, write)

    monkeypatch.setattr(
        InProcessGenerationRunLauncher,
        "_claim_for_failure",
        claim_for_failure,
    )
    monkeypatch.setattr(
        InProcessGenerationRunLauncher,
        "_write_failure",
        write_failure,
    )

    result = await run_launcher._record_failure(
        run_id,
        Failure("transactional", "unexpected"),
        RunClaim(),
    )

    assert result.written is True, result
    assert seen["claim"] is seen["write"], "claim and write must share a unit of work"
    run, kinds = await _load(session_factory, run_id)
    assert kinds.count("run.failed") == 1, kinds
    assert run.status is GenerationRunStatus.FAILED, run.status


@pytest.mark.asyncio
async def test_blocked_reconciliation_then_second_cancellation(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second cancellation while reconciliation is blocked still records."""
    from episodic.generation.launcher import InProcessGenerationRunLauncher

    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = _launcher(session_factory)
    claim = RunClaim()
    await run_launcher._claim_and_start(run_id, claim)
    claim.token = None

    original = InProcessGenerationRunLauncher._reconcile_claim
    gate = asyncio.Event()
    release = asyncio.Event()

    async def blocked_reconcile(
        self: InProcessGenerationRunLauncher,
        run_id: uuid.UUID,
        candidate: RunClaim,
    ) -> ClaimToken | None:
        """Block reconciliation until the test releases it."""
        gate.set()
        await release.wait()
        return await original(self, run_id, candidate)

    monkeypatch.setattr(
        InProcessGenerationRunLauncher,
        "_reconcile_claim",
        blocked_reconcile,
    )

    write_task = asyncio.create_task(
        run_launcher._record_cancellation_owned(run_id, claim),
    )
    await asyncio.wait_for(gate.wait(), timeout=5)
    # A second cancellation reaches the same path while reconcile is blocked;
    # the pending marker makes it a no-op rather than a fresh claim attempt.
    await run_launcher._record_cancellation_owned(run_id, claim)
    release.set()
    await asyncio.wait_for(write_task, timeout=5)

    run, kinds = await _load(session_factory, run_id)
    assert kinds.count("run.failed") == 1, kinds
    assert run.status is GenerationRunStatus.FAILED, run.status
    assert claim.token is not None, claim


class _RefusingPorts:
    """Session ports whose failure write is refused."""

    uow_factory = staticmethod(lambda: None)
    clock = staticmethod(lambda: None)
    metrics = types.SimpleNamespace(increment_counter=lambda *a, **k: None)

    async def _record_failure(self, *args: object, **kwargs: object) -> object:
        """Refuse the write."""
        _ = (args, kwargs)
        from episodic.generation.launcher_support import FailureWriteResult

        return FailureWriteResult(written=False)


@pytest.mark.asyncio
async def test_escalation_propagates_a_refused_write() -> None:
    """A refused escalation write is not treated as recorded."""
    from episodic.canonical.generation_quality import QaStatus
    from episodic.canonical.generation_routing import QualityVerdict
    from episodic.generation.launcher_session import (
        RunNotClaimedError,
        _LauncherRunSession,
    )
    from tests.generation_run_launcher_support import draft_result, valid_tei

    session = _LauncherRunSession(
        launcher=typ.cast("typ.Any", _RefusingPorts()),
        run_id=uuid.uuid4(),
        claim=RunClaim(token=ClaimToken(uuid.uuid4())),
    )
    session.draft = draft_result(valid_tei())

    with pytest.raises(RunNotClaimedError, match="refused the escalation"):
        await session.escalate(QualityVerdict.FAILED, ())
    _ = QaStatus


@pytest.mark.asyncio
async def test_reconcile_rejects_another_attempts_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A loser with the same start timestamp does not adopt the claim."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    winner_launcher = _launcher(session_factory)
    loser_launcher = _launcher(session_factory)
    winner = RunClaim()
    await winner_launcher._claim_and_start(run_id, winner)

    loser = RunClaim()
    loser.started_at = winner.started_at  # the test clock is frozen
    lost = await loser_launcher._claim_and_start(run_id, loser)
    assert lost is None, lost
    reconciled = await loser_launcher._reconcile_claim(run_id, loser)
    assert reconciled is None, reconciled
    assert loser.token is None, loser.token


@pytest.mark.asyncio
async def test_pending_tokenless_marker_does_not_suppress_a_token_holder(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A marker left by a tokenless attempt cannot block the claimant's write."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = _launcher(session_factory)
    claim = RunClaim()
    await run_launcher._claim_and_start(run_id, claim)

    # Simulate a tokenless duplicate that registered a marker and then could
    # not write. The claimant's token must still be honoured.
    run_launcher._pending_cancellation_ids.add(run_id)
    await run_launcher._record_cancellation_owned(run_id, claim)

    run, kinds = await _load(session_factory, run_id)
    assert kinds.count("run.failed") == 1, kinds
    assert run.status is GenerationRunStatus.FAILED, run.status
    assert run.error_category == "launcher.shutdown", run.error_category
