"""Shared behavioural contracts for generation-run checkpoint adapters.

Each scenario is a plain coroutine rather than a method on a ``Test``-prefixed
class. A class in a module pytest does not collect is still collected once the
module is imported into a collected one, under the *importer's* namespace, so a
shared base class would run its fixtures in the wrong context. Functions have
no such trap, and this module is deliberately named so pytest does not collect
it directly.

Every scenario is driven twice — against the in-memory reference adapter and
against the SQLAlchemy composite — so a divergence fails a test rather than
passing unnoticed. The adapters differ in where state lives, so each scenario
receives hooks that absorb the difference:

``prepare_run``
    Persist the foreign-key prerequisites a run needs: a no-op in memory, but
    under PostgreSQL the series, episode, and ingestion job that
    ``generation_runs`` references must be committed first.
``read_fresh``
    Read a checkpoint back through a *new* unit of work, so the scenario only
    observes committed state. A no-op lookup in memory.
``count_checkpoints``
    Count persisted rows for one identifier, which is how a rejected create is
    shown to have written nothing rather than merely to have raised.

Scenarios assert on the entity the domain transition returned as well as on a
fresh read. INV-CKPT-1 is about the adapter persisting what the domain
computed, not about recomputing it, so a re-read alone would not distinguish
the two.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import (
    Checkpoint,
    CheckpointAction,
    CheckpointResponse,
    CheckpointStatus,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_errors import (
    CheckpointAlreadyExists,
    CheckpointAlreadyTerminal,
    CheckpointNotFound,
    RunNotFound,
)
from episodic.canonical.generation_run_ports import (
    GenerationCheckpointPort,
    GenerationRunPort,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

#: One instant for every scenario, so equality comparisons stay exact.
NOW = dt.datetime(2026, 6, 24, 8, 30, tzinfo=dt.UTC)

#: Deliberately not alphabetical: a set or sort round-trip becomes visible.
OPTIONS = ("request_changes", "edit", "approve")

#: The instant each transition records, asserted exactly by the scenarios.
RESPONDED_AT = NOW + dt.timedelta(minutes=1)
TIMED_OUT_AT = NOW + dt.timedelta(minutes=30)
CANCELLED_AT = NOW + dt.timedelta(minutes=20)

type PrepareRun = cabc.Callable[[GenerationRun], cabc.Awaitable[None]]
type ReadFresh = cabc.Callable[[uuid.UUID], cabc.Awaitable[Checkpoint | None]]
type CountCheckpoints = cabc.Callable[[uuid.UUID], cabc.Awaitable[int]]
type Apply = cabc.Callable[[GenerationRunPort, uuid.UUID], cabc.Awaitable[Checkpoint]]


def make_run(run_id: uuid.UUID | None = None) -> GenerationRun:
    """Build a pending generation run with deterministic timestamps."""
    return GenerationRun(
        id=run_id or uuid.uuid7(),
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


# Terminal states are populated with the fields their invariants require, so a
# scenario receives a genuine terminal checkpoint rather than a `ValueError`
# from `__post_init__`: the domain demands all three response fields for
# RESPONDED, while TIMED_OUT and CANCELLED record only the resolving instant.
def make_checkpoint(
    run_id: uuid.UUID,
    *,
    checkpoint_id: uuid.UUID | None = None,
    status: CheckpointStatus = CheckpointStatus.CREATED,
) -> Checkpoint:
    """Build a valid review checkpoint in the given lifecycle state."""
    is_responded = status is CheckpointStatus.RESPONDED
    is_resolved = status is not CheckpointStatus.CREATED
    return Checkpoint(
        id=checkpoint_id or uuid.uuid7(),
        generation_run_id=run_id,
        node="review",
        prompt="Approve the draft?",
        options=OPTIONS,
        status=status,
        created_at=NOW,
        responded_at=RESPONDED_AT if is_resolved else None,
        responded_by="reviewer@example.com" if is_responded else None,
        response_action=CheckpointAction.APPROVE if is_responded else None,
        response_payload={},
    )


def make_response(*, offset_minutes: int = 1) -> CheckpointResponse:
    """Build an approving reviewer response carrying a nested payload.

    The payload holds a nested mapping and a list, so that a JSONB round-trip
    which flattens or reorders either one is caught rather than tolerated.

    Returns
    -------
    CheckpointResponse
        Response object suitable for ``respond_to_checkpoint``.
    """
    return CheckpointResponse(
        action=CheckpointAction.APPROVE,
        payload={"approved": True, "notes": ["alpha", "beta"]},
        responded_at=NOW + dt.timedelta(minutes=offset_minutes),
        responded_by="reviewer@example.com",
    )


async def respond(store: GenerationRunPort, checkpoint_id: uuid.UUID) -> Checkpoint:
    """Apply the reviewer-response transition."""
    return await store.respond_to_checkpoint(
        checkpoint_id,
        response=make_response(offset_minutes=1),
    )


async def time_out(store: GenerationRunPort, checkpoint_id: uuid.UUID) -> Checkpoint:
    """Apply the timeout transition."""
    return await store.time_out_checkpoint(checkpoint_id, at=TIMED_OUT_AT)


async def cancel(store: GenerationRunPort, checkpoint_id: uuid.UUID) -> Checkpoint:
    """Apply the cancellation transition."""
    return await store.cancel_checkpoint(checkpoint_id, at=CANCELLED_AT)


@dc.dataclass(frozen=True, slots=True)
class Transition:
    """One checkpoint transition, named for test identifiers.

    ``resolved_at`` is the instant the transition must record. Asserting it
    exactly, rather than merely asserting a timestamp exists, is what makes a
    truncated or timezone-shifted round-trip visible (INV-CKPT-3).
    """

    name: str
    apply: Apply
    expected: CheckpointStatus
    resolved_at: dt.datetime


#: Every transition a caller can apply to a live checkpoint.
TRANSITIONS = (
    Transition("respond", respond, CheckpointStatus.RESPONDED, RESPONDED_AT),
    Transition("time_out", time_out, CheckpointStatus.TIMED_OUT, TIMED_OUT_AT),
    Transition("cancel", cancel, CheckpointStatus.CANCELLED, CANCELLED_AT),
)

#: Test identifiers for `TRANSITIONS`, so a driver names the case it drives
#: with `ids=TRANSITION_IDS` rather than deriving the name at the call site.
TRANSITION_IDS = tuple(transition.name for transition in TRANSITIONS)

#: The three states from which a checkpoint can no longer transition.
TERMINAL_STATUSES = (
    CheckpointStatus.RESPONDED,
    CheckpointStatus.TIMED_OUT,
    CheckpointStatus.CANCELLED,
)


@dc.dataclass(frozen=True, slots=True)
class TerminalCase:
    """One terminal starting state plus one further transition."""

    start: Transition
    transition: Transition


#: All nine combinations of a terminal state and a further transition.
TERMINAL_CASES = tuple(
    TerminalCase(start, transition)
    for start in TRANSITIONS
    for transition in TRANSITIONS
)

#: Test identifiers for `TERMINAL_CASES`, naming both halves of the case.
TERMINAL_CASE_IDS = tuple(
    f"{case.start.name}+{case.transition.name}" for case in TERMINAL_CASES
)


async def scenario_store_satisfies_generation_run_port(  # ruff: ignore[unused-async]  # Shares the scenario calling convention, so it must be a coroutine.
    store: GenerationRunPort,
) -> None:
    """Check the adapter satisfies the composite port and its checkpoint port."""
    assert isinstance(store, GenerationCheckpointPort), "checkpoint sub-port"
    assert isinstance(store, GenerationRunPort), "composite port"


async def scenario_creation_persists_checkpoint(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
) -> None:
    """Create a checkpoint that is still readable in a later unit of work."""
    run = make_run()
    await prepare_run(run)
    await store.create_run(run)

    created = await store.create_checkpoint(make_checkpoint(run.id))

    assert created.status is CheckpointStatus.CREATED, f"status: {created.status}"
    assert created.options == OPTIONS, f"option order: {created.options!r}"
    assert await read_fresh(created.id) == created, "committed row must match"


async def scenario_transition_persists_domain_result(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
    transition: Transition,
) -> None:
    """Persist exactly the entity the domain transition produced."""
    run = make_run()
    await prepare_run(run)
    await store.create_run(run)
    created = await store.create_checkpoint(make_checkpoint(run.id))

    updated = await transition.apply(store, created.id)

    assert updated.status is transition.expected, f"status: {updated.status}"
    assert updated.responded_at == transition.resolved_at, (
        f"resolved_at: {updated.responded_at!r}"
    )
    assert await read_fresh(created.id) == updated, "fresh read must match"


async def scenario_response_round_trips_payload(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
) -> None:
    """Round-trip the reviewer action, identity, and nested payload."""
    run = make_run()
    await prepare_run(run)
    await store.create_run(run)
    created = await store.create_checkpoint(make_checkpoint(run.id))

    responded = await respond(store, created.id)

    assert responded.response_action is CheckpointAction.APPROVE, (
        f"action: {responded.response_action!r}"
    )
    assert responded.responded_by == "reviewer@example.com", (
        f"responded_by: {responded.responded_by!r}"
    )
    assert responded.response_payload["notes"] == ["alpha", "beta"], (
        f"payload: {responded.response_payload!r}"
    )
    assert await read_fresh(created.id) == responded, "payload must survive commit"


async def scenario_terminal_checkpoint_rejects_transition(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
    case: TerminalCase,
) -> None:
    """Reject every further transition on a terminal checkpoint.

    The re-read is the substance of the assertion: without it the scenario
    would pass even if the adapter wrote the mutation and then raised.
    """
    run = make_run()
    await prepare_run(run)
    await store.create_run(run)
    created = await store.create_checkpoint(make_checkpoint(run.id))
    reached = await case.start.apply(store, created.id)

    with pytest.raises(CheckpointAlreadyTerminal):
        await case.transition.apply(store, created.id)

    assert await read_fresh(created.id) == reached, "terminal state must not change"


async def scenario_transition_rejects_unknown_checkpoint(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
    transition: Transition,
) -> None:
    """Refuse a transition for an identifier that was never stored."""
    run = make_run()
    await prepare_run(run)
    await store.create_run(run)

    with pytest.raises(CheckpointNotFound):
        await transition.apply(store, uuid.uuid7())


async def scenario_creation_rejects_unknown_run(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
    count_checkpoints: CountCheckpoints,
) -> None:
    """Fail without writing a row when the parent run does not exist.

    The row count is asserted as well as the exception: an adapter that
    mistranslated a foreign-key ``IntegrityError`` after a partial write would
    otherwise pass.
    """
    orphan = make_run()
    await prepare_run(orphan)
    checkpoint = make_checkpoint(orphan.id)

    with pytest.raises(RunNotFound):
        await store.create_checkpoint(checkpoint)

    assert await count_checkpoints(checkpoint.id) == 0, "no row may be written"


async def scenario_creation_rejects_duplicate_identifier(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
    read_fresh: ReadFresh,
) -> None:
    """Refuse a second checkpoint under an identifier already in use.

    The overwrite this guards against is specifically a terminal checkpoint
    being reset to ``created`` by a replayed create, so the first checkpoint is
    responded to before the duplicate is attempted.
    """
    run = make_run()
    await prepare_run(run)
    await store.create_run(run)
    checkpoint_id = uuid.uuid7()
    await store.create_checkpoint(make_checkpoint(run.id, checkpoint_id=checkpoint_id))
    answered = await respond(store, checkpoint_id)

    with pytest.raises(CheckpointAlreadyExists):
        await store.create_checkpoint(
            make_checkpoint(run.id, checkpoint_id=checkpoint_id)
        )

    assert await read_fresh(checkpoint_id) == answered, "original row must survive"


async def scenario_creation_rejects_terminal_status(
    store: GenerationRunPort,
    *,
    prepare_run: PrepareRun,
    status: CheckpointStatus,
) -> None:
    """Refuse to create a checkpoint that arrives already terminal."""
    run = make_run()
    await prepare_run(run)
    await store.create_run(run)

    with pytest.raises(CheckpointAlreadyTerminal):
        await store.create_checkpoint(make_checkpoint(run.id, status=status))
