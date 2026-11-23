"""Claim-token authority and cancellation-write ordering (INV-9).

These tests exercise the token that authorizes a terminal failure write, the
reconciliation of a lost commit acknowledgement, and the tracking that makes
shutdown wait for a shielded cancellation write.
"""

import asyncio
import contextlib
import dataclasses as dc
import types
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.launcher_support import ClaimToken, Failure, RunClaim
from tests.generation_run_launcher_observation_support import RecordingMetrics
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

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.launcher import InProcessGenerationRunLauncher
    from episodic.generation.launcher_support import FailureWrite


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


def _launcher(
    session_factory: async_sessionmaker[AsyncSession],
    fault: CommitFault | None = None,
) -> InProcessGenerationRunLauncher:
    """Build a launcher, optionally over the commit-fault unit of work."""
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
    )
    if fault is None:
        return run_launcher
    return dc.replace(
        run_launcher,
        uow_factory=lambda: CommitFaultUnitOfWork(session_factory, fault),
    )


@pytest.mark.asyncio
async def test_failure_write_authority_comes_from_the_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A token, not shared state, is what lets a failure be written.

    The same run is offered to two invocations: one holds the token its claim
    produced and writes; the other holds an empty claim and is refused, and
    the refused call must leave no trace.
    """
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
    )

    holder = RunClaim()
    await run_launcher._claim_and_start(run_id, holder)
    assert holder.token is not None, "a won claim must produce a token"

    refused = await run_launcher._record_failure(
        run_id,
        Failure("not mine", "unexpected"),
        claim=RunClaim(),
    )
    run, kinds = await _load(session_factory, run_id)
    assert refused.written is False, "a claim without a token must not write"
    assert kinds == ["run.started"], kinds
    assert run.status is GenerationRunStatus.RUNNING, run.status

    written = await run_launcher._record_failure(
        run_id,
        Failure("mine", "unexpected"),
        claim=holder,
    )
    run, kinds = await _load(session_factory, run_id)
    assert written.written is True, "the token holder must be able to write"
    assert kinds == ["run.started", "run.failed"], kinds
    assert run.error_message == "mine", run.error_message


def test_claim_tokens_are_immutable() -> None:
    """The authority value cannot be altered after it is issued."""
    token = ClaimToken(uuid.uuid4())
    with pytest.raises(dc.FrozenInstanceError):
        typ.cast("typ.Any", token).run_id = uuid.uuid4()


@pytest.mark.asyncio
async def test_refused_write_records_no_metric_or_failure_log(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refused write leaves no terminal metric and no failure log."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    metrics = RecordingMetrics()
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
    )
    run_launcher.metrics = metrics
    holder = RunClaim()
    await run_launcher._claim_and_start(run_id, holder)

    with caplog.at_level("ERROR"):
        result = await run_launcher._record_failure(
            run_id,
            Failure("not mine", "unexpected"),
            claim=RunClaim(),
        )

    assert result.written is False, result
    counters = [
        observation
        for observation in metrics.observations
        if observation.kind == "counter"
        and observation.name == "generation_run_terminal_total"
    ]
    assert counters == [], counters
    assert "generation_run_launcher.failed" not in caplog.text, caplog.text


@pytest.mark.asyncio
async def test_failure_write_without_a_claim_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The failure path has no implicit authority default."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = launcher(
        session_factory,
        RecordingDraftGenerator(draft_result(valid_tei())),
        options=LauncherOptions(evaluator_set=QualityEvaluatorSet(())),
    )

    untyped = typ.cast("typ.Any", run_launcher._record_failure)
    with pytest.raises(TypeError):
        await untyped(run_id, Failure("no claim", "unexpected"))


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
    ) -> ClaimToken | None:
        """Record the unit of work used for the claim."""
        seen["claim"] = uow
        return await original_claim(self, uow, failed_run_id)

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
