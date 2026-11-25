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
    await run_launcher._components()[0].claim(run_id, holder)
    assert holder.token is not None, "a won claim must produce a token"

    refused = await run_launcher._components()[2].record_failure(
        run_id,
        Failure("not mine", "unexpected"),
        claim=RunClaim(),
    )
    run, kinds = await _load(session_factory, run_id)
    assert refused.written is False, "a claim without a token must not write"
    assert kinds == ["run.started"], kinds
    assert run.status is GenerationRunStatus.RUNNING, run.status

    written = await run_launcher._components()[2].record_failure(
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
    await run_launcher._components()[0].claim(run_id, holder)

    with caplog.at_level("ERROR"):
        result = await run_launcher._components()[2].record_failure(
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
    failures = run_launcher._components()[2]
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

    result = await run_launcher._components()[2].record_failure(
        this_run,
        Failure("foreign token", "unexpected"),
        claim=handed_over,
    )

    assert result.written is False, result
    run, kinds = await _load(session_factory, this_run)
    assert run.status is GenerationRunStatus.PENDING, kinds
    assert "run.failed" not in kinds, kinds
    assert run.error_category is None, run.error_category


@pytest.mark.asyncio
async def test_the_observer_runs_once_after_a_committed_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The observe callback runs once, after the write commits."""
    run_id, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = _launcher(session_factory)
    failures = run_launcher._components()[2]
    seen: list[tuple[uuid.UUID, Failure]] = []
    failure = Failure("observed", "unexpected")
    failures.observe = lambda observed_id, observed_failure: seen.append(
        (observed_id, observed_failure),
    )

    result = await failures.record_failure(run_id, failure, claim=RunClaim())

    assert result.written is True, result
    assert seen == [(run_id, failure)], seen


@pytest.mark.asyncio
async def test_the_observer_does_not_run_for_a_refused_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A refused write commits nothing, so the observer never runs."""
    this_run, _ = await prepare_pending_qa_gated_run(session_factory)
    run_launcher = _launcher(session_factory)
    failures = run_launcher._components()[2]
    seen: list[uuid.UUID] = []
    failures.observe = lambda observed_id, _failure: seen.append(observed_id)

    result = await failures.record_failure(
        this_run,
        Failure("foreign token", "unexpected"),
        claim=RunClaim(token=ClaimToken(uuid.uuid4())),
    )

    assert result.written is False, result
    assert not seen, seen


def test_an_injected_proof_factory_supplies_the_proof() -> None:
    """A caller-supplied proof factory decides the claim proof."""
    fixed = uuid.uuid4()

    claim = RunClaim(proof_factory=lambda: fixed)

    assert claim.proof == fixed, claim.proof
