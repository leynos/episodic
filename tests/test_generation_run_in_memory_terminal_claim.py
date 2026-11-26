"""The in-memory store's terminal-claim gate, tested directly (INV-9).

The SQL adapter's gate has its own contract tests. The reference adapter
enforces the same rule through ``require_terminal_claim``, so it needs the same
evidence: a claimed run may only be terminated by its own token, an unclaimed
run may be terminated by an internal path, and non-terminal updates need no
token at all.
"""

import datetime as dt
import uuid

import pytest

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_claim import ExecutionClaim
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_errors import RunClaimMismatch
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)


def _store() -> InMemoryGenerationRunStore:
    """Create a deterministic in-memory store."""
    return InMemoryGenerationRunStore(time_provider=lambda: NOW)


def _run() -> GenerationRun:
    """Build a pending no-QA run for the gate tests."""
    return GenerationRun(
        id=uuid.uuid7(),
        episode_id=uuid.uuid7(),
        source_bundle_id=uuid.uuid7(),
        actor="editor@example.com",
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={},
        configuration={},
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
    )


def _claim(proof: uuid.UUID | None) -> ExecutionClaim:
    """Build the claim a launcher would send, with an optional proof."""
    return ExecutionClaim(
        current_node="draft",
        started_at=NOW,
        lease_expires_at=NOW + dt.timedelta(minutes=5),
        claim_token=proof,
    )


def _terminal(
    status: GenerationRunStatus,
    claim_token: uuid.UUID | None,
) -> GenerationRunStatusUpdate:
    """Build a terminal status update carrying an optional claim token."""
    return GenerationRunStatusUpdate(
        status=status,
        current_node=None,
        ended_at=NOW,
        qa_status=QaStatus.SKIPPED,
        claim_token=claim_token,
    )


@pytest.mark.asyncio
async def test_claim_token_for_reports_the_stored_proof_and_nothing_else() -> None:
    """The store reports a claimed run's proof, and ``None`` otherwise."""
    store = _store()
    run = await store.create_run(_run())
    proof = uuid.uuid4()

    assert await store.claim_token_for(run.id) is None, "the run starts unclaimed"
    await store.claim_run_for_execution(run.id, _claim(proof))

    stored_proof = await store.claim_token_for(run.id)
    assert stored_proof == proof, stored_proof
    assert await store.claim_token_for(uuid.uuid4()) is None, "unknown run"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "supplied",
    [None, uuid.uuid4()],
    ids=["absent", "wrong"],
)
async def test_a_claimed_run_refuses_a_terminal_write_without_its_token(
    supplied: uuid.UUID | None,
) -> None:
    """A missing or foreign token cannot terminate a claimed run."""
    store = _store()
    run = await store.create_run(_run())
    proof = uuid.uuid4()
    await store.claim_run_for_execution(run.id, _claim(proof))

    with pytest.raises(RunClaimMismatch) as excinfo:
        await store.update_run_status(
            run.id,
            update=_terminal(GenerationRunStatus.SUCCEEDED, supplied),
        )

    assert str(run.id) in str(excinfo.value), excinfo.value
    stored = await store.get_run(run.id)
    assert stored is not None, "the refused write must not remove the run"
    assert stored.status is GenerationRunStatus.RUNNING, stored.status


@pytest.mark.asyncio
async def test_the_stored_token_terminates_the_run() -> None:
    """The claiming token authorizes the terminal transition."""
    store = _store()
    run = await store.create_run(_run())
    proof = uuid.uuid4()
    await store.claim_run_for_execution(run.id, _claim(proof))

    updated = await store.update_run_status(
        run.id,
        update=_terminal(GenerationRunStatus.FAILED, proof),
    )

    assert updated.status is GenerationRunStatus.FAILED, updated.status


@pytest.mark.asyncio
async def test_an_unclaimed_run_needs_no_token_to_terminate() -> None:
    """A run that never stored a claim has no owner to check."""
    store = _store()
    run = await store.create_run(_run())

    updated = await store.update_run_status(
        run.id,
        update=_terminal(GenerationRunStatus.FAILED, None),
    )

    assert updated.status is GenerationRunStatus.FAILED, updated.status


@pytest.mark.asyncio
async def test_a_non_terminal_update_needs_no_token() -> None:
    """Only terminal transitions are fenced."""
    store = _store()
    run = await store.create_run(_run())
    proof = uuid.uuid4()
    await store.claim_run_for_execution(run.id, _claim(proof))

    updated = await store.update_run_status(
        run.id,
        update=GenerationRunStatusUpdate(
            status=GenerationRunStatus.RUNNING,
            current_node="evaluate",
            ended_at=None,
        ),
    )

    assert updated.current_node == "evaluate", updated.current_node
