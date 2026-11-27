"""Claim-token authority and cancellation-write ordering (INV-9).

These tests exercise the token that authorizes a terminal failure write, the
reconciliation of a lost commit acknowledgement, and the tracking that makes
shutdown wait for a shielded cancellation write.
"""

import dataclasses as dc
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation import launcher_failure
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

    from episodic.generation.launcher import InProcessGenerationRunLauncher
    from episodic.generation.launcher_failure import CommittedFailure


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
    claimed = await run_launcher._components[0].claim(run_id, holder)
    assert claimed is not None, "the run must be claimed"
    assert claimed.token.run_id == run_id, claimed.token

    refused = await run_launcher._components[2].record_failure(
        run_id,
        Failure("not mine", "unexpected"),
        claim=RunClaim(),
    )
    run, kinds = await _load(session_factory, run_id)
    assert refused.written is False, "a claim without a token must not write"
    assert kinds == ["run.started"], kinds
    assert run.status is GenerationRunStatus.RUNNING, run.status

    written = await run_launcher._components[2].record_failure(
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
    await run_launcher._components[0].claim(run_id, holder)

    with caplog.at_level("ERROR"):
        result = await run_launcher._components[2].record_failure(
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
    failures = run_launcher._components[2]
    untyped = typ.cast("typ.Any", failures.record_failure)

    with pytest.raises(TypeError):
        await untyped(run_id, Failure("no claim", "unexpected"))


@pytest.mark.asyncio
async def test_a_token_for_another_run_cannot_fail_this_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A cached token naming another run must not authorize this failure."""
    this_run, _ = await prepare_pending_qa_gated_run(session_factory)
    other_run_id = uuid.uuid4()
    run_launcher = _launcher(session_factory)
    handed_over = RunClaim(token=ClaimToken(other_run_id))

    result = await run_launcher._components[2].record_failure(
        this_run,
        Failure("foreign token", "unexpected"),
        claim=handed_over,
    )

    assert result.written is False, result
    run, kinds = await _load(session_factory, this_run)
    assert run.status is GenerationRunStatus.PENDING, kinds
    assert "run.failed" not in kinds, kinds
    assert run.error_category is None, run.error_category


@dc.dataclass(slots=True)
class _CommitWatch:
    """Record whether a unit of work has committed."""

    committed: bool = False


class _WatchingUnitOfWork(SqlAlchemyUnitOfWork):
    """Unit of work that records when its commit returns."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        watch: _CommitWatch,
    ) -> None:
        """Open the real unit of work with the supplied commit watch."""
        super().__init__(session_factory)
        self._watch = watch

    async def commit(self) -> None:
        """Commit, then record that the write is durable."""
        await super().commit()
        self._watch.committed = True


class _RaisingCommitUnitOfWork(SqlAlchemyUnitOfWork):
    """Unit of work whose first commit raises before it reaches the database."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        watch: _CommitWatch,
    ) -> None:
        """Open the real unit of work with the supplied watch."""
        super().__init__(session_factory)
        self._watch = watch
        self._should_raise = True

    async def commit(self) -> None:
        """Raise once, then commit normally."""
        if self._should_raise:
            self._should_raise = False
            msg = "commit fault"
            raise RuntimeError(msg)
        await super().commit()
        self._watch.committed = True


def _capture_notifications(
    monkeypatch: pytest.MonkeyPatch,
    watch: _CommitWatch | None,
) -> list[tuple[uuid.UUID, Failure, bool]]:
    """Replace the post-commit notifier and record each committed result.

    Returns
    -------
    list[tuple[uuid.UUID, Failure, bool]]
        One entry per notification: the run, the failure, and whether the
        commit had returned when the notifier ran.
    """
    seen: list[tuple[uuid.UUID, Failure, bool]] = []

    def capture(metrics: object, committed: object) -> None:
        """Record one notification and the commit state it observed."""
        _ = metrics
        entry = typ.cast("CommittedFailure", committed)
        seen.append((entry.run_id, entry.failure, watch is None or watch.committed))

    monkeypatch.setattr(launcher_failure, "notify_committed_failure", capture)
    return seen


@pytest.mark.asyncio
async def test_the_notifier_runs_once_after_a_committed_failure(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The notifier runs once, and only after the commit has returned.

    The notifier records the commit watch at the moment it runs, so moving the
    call before the commit fails this test.
    """
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    watch = _CommitWatch()
    run_launcher = dc.replace(
        _launcher(session_factory),
        uow_factory=lambda: _WatchingUnitOfWork(session_factory, watch),
    )
    failures = run_launcher._components[2]
    seen = _capture_notifications(monkeypatch, watch)
    failure = Failure("observed", "unexpected")

    result = await failures.record_failure(run_id, failure, claim=RunClaim())

    assert result.written is True, result
    assert seen == [(run_id, failure, True)], seen


@pytest.mark.asyncio
async def test_the_notifier_does_not_run_for_a_refused_write(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused write commits nothing, so the notifier never runs."""
    this_run, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = _launcher(session_factory)
    failures = run_launcher._components[2]
    seen = _capture_notifications(monkeypatch, None)

    result = await failures.record_failure(
        this_run,
        Failure("foreign token", "unexpected"),
        claim=RunClaim(token=ClaimToken(uuid.uuid4())),
    )

    assert result.written is False, result
    assert not seen, seen


@pytest.mark.asyncio
async def test_the_notifier_never_runs_when_the_commit_raises(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write that raises before committing notifies nothing and persists nothing."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    watch = _CommitWatch()
    run_launcher = dc.replace(
        _launcher(session_factory),
        uow_factory=lambda: _RaisingCommitUnitOfWork(session_factory, watch),
    )
    failures = run_launcher._components[2]
    seen = _capture_notifications(monkeypatch, watch)

    with pytest.raises(RuntimeError, match="commit fault"):
        await failures.record_failure(
            run_id,
            Failure("uncommitted", "unexpected"),
            claim=RunClaim(),
        )

    assert watch.committed is False, "the fault must precede the commit"
    assert not seen, seen
    _run, kinds = await _load(session_factory, run_id)
    assert "run.failed" not in kinds, kinds


def test_an_injected_proof_factory_supplies_the_proof() -> None:
    """A caller-supplied proof factory decides the claim proof."""
    fixed = uuid.uuid4()

    claim = RunClaim(proof_factory=lambda: fixed)

    assert claim.proof == fixed, claim.proof
