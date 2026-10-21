"""Fidelity coverage for the SQL review-checkpoint store.

``tests/generation_run_contract_scenarios.py`` is a *shape* check: the in-memory
adapter stores whole frozen dataclasses behind an ``asyncio.Lock``, so it
structurally cannot exhibit timezone truncation, JSONB round-trip shape,
tuple-versus-list coercion, or foreign-key violations. This module carries the
real fidelity evidence for INV-CKPT-3, and the commit-safety evidence for
INV-COMMIT-1 that no adapter comparison can express.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import (
    Checkpoint,
    CheckpointAction,
    CheckpointResponse,
    CheckpointStatus,
    GenerationRun,
    GenerationRunStatus,
    SeriesProfile,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork, uow
from tests import generation_run_checkpoint_listing_scenarios as listing
from tests.canonical_storage._generation_run_support import (
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = dt.datetime(2026, 6, 24, 8, 30, tzinfo=dt.UTC)

#: Deliberately not alphabetical, so a set or sort round-trip becomes visible.
OPTIONS = ("edit", "approve", "request_changes")

#: A nested mapping plus a list, so a JSONB round trip that flattens either one
#: is caught rather than tolerated.
PAYLOAD = {
    "approved": True,
    "notes": ["alpha", "beta"],
    "annotations": {"target": "section-3", "spans": [1, 2, 3]},
}


def _run() -> GenerationRun:
    """Build a pending generation run with deterministic timestamps."""
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


def _checkpoint(run_id: uuid.UUID) -> Checkpoint:
    """Build a created checkpoint carrying the non-alphabetical options."""
    return Checkpoint(
        id=uuid.uuid7(),
        generation_run_id=run_id,
        node="review",
        prompt="Approve the draft?",
        options=OPTIONS,
        status=CheckpointStatus.CREATED,
        created_at=NOW,
        responded_at=None,
        responded_by=None,
        response_action=None,
        response_payload={},
    )


@dc.dataclass(frozen=True, slots=True)
class Committed:
    """A run and checkpoint already committed to PostgreSQL."""

    run_id: uuid.UUID
    checkpoint_id: uuid.UUID


async def _commit_run_and_checkpoint(
    session_factory: async_sessionmaker[AsyncSession],
) -> Committed:
    """Commit a run with its foreign keys and one created checkpoint."""
    run = _run()
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        created = await uow.generation_runs.create_checkpoint(_checkpoint(run.id))
        await uow.commit()
    return Committed(run_id=run.id, checkpoint_id=created.id)


async def _read_fresh(
    session_factory: async_sessionmaker[AsyncSession],
    checkpoint_id: uuid.UUID,
) -> Checkpoint | None:
    """Read a checkpoint back through a brand-new unit of work."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        return await uow.generation_runs.get_checkpoint(checkpoint_id)


async def _prepare_run(
    session_factory: async_sessionmaker[AsyncSession],
    run: GenerationRun,
) -> None:
    """Commit the series, episode, and job a run's foreign keys need."""
    await persist_generation_run_prerequisites(session_factory, run)


@pytest.mark.asyncio
async def test_listing_returns_checkpoints_oldest_created_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The SQL listing orders checkpoints by ``(created_at, id)``."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow_instance:
        await listing.scenario_listing_returns_checkpoints_oldest_created_first(
            uow_instance.generation_runs,
            prepare_run=lambda run: _prepare_run(session_factory, run),
        )


@pytest.mark.asyncio
async def test_listing_filters_by_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The SQL listing's status filter selects only matching checkpoints."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow_instance:
        await listing.scenario_listing_filters_by_status(
            uow_instance.generation_runs,
            prepare_run=lambda run: _prepare_run(session_factory, run),
        )


@pytest.mark.asyncio
async def test_listing_applies_bounds_within_a_status_filter(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The SQL listing paginates the filtered result, not the stored rows."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow_instance:
        await listing.scenario_listing_applies_bounds_within_a_status_filter(
            uow_instance.generation_runs,
            prepare_run=lambda run: _prepare_run(session_factory, run),
        )


@pytest.mark.asyncio
async def test_listing_rejects_unknown_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Listing for a run that was never stored raises ``RunNotFound``."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow_instance:
        await listing.scenario_listing_rejects_unknown_run(
            uow_instance.generation_runs,
            prepare_run=lambda run: _prepare_run(session_factory, run),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "offset"),
    listing.NEGATIVE_BOUND_CASES,
    ids=["negative-limit", "negative-offset"],
)
async def test_listing_rejects_negative_bounds(
    session_factory: async_sessionmaker[AsyncSession],
    limit: int,
    offset: int,
) -> None:
    """A negative ``limit`` or ``offset`` is refused, not clamped."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow_instance:
        await listing.scenario_listing_rejects_negative_bounds(
            uow_instance.generation_runs,
            prepare_run=lambda run: _prepare_run(session_factory, run),
            limit=limit,
            offset=offset,
        )


@pytest.mark.asyncio
async def test_options_keep_their_order_across_a_fresh_unit_of_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The options tuple round-trips in order, not sorted or set-ified."""
    committed = await _commit_run_and_checkpoint(session_factory)

    reloaded = await _read_fresh(session_factory, committed.checkpoint_id)

    assert reloaded is not None, "the committed checkpoint must be readable"
    assert reloaded.options == OPTIONS, f"option order: {reloaded.options!r}"
    assert isinstance(reloaded.options, tuple), (
        "options must be restored as a tuple, not a JSON list"
    )


@pytest.mark.asyncio
async def test_nested_payload_round_trips_through_jsonb(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A nested mapping and a list survive JSONB without being flattened."""
    committed = await _commit_run_and_checkpoint(session_factory)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.respond_to_checkpoint(
            committed.checkpoint_id,
            response=CheckpointResponse(
                action=CheckpointAction.APPROVE,
                payload=dict(PAYLOAD),
                responded_at=NOW + dt.timedelta(minutes=1),
                responded_by="reviewer@example.com",
            ),
        )
        await uow.commit()

    reloaded = await _read_fresh(session_factory, committed.checkpoint_id)

    assert reloaded is not None, "the committed checkpoint must be readable"
    assert reloaded.response_payload == PAYLOAD, (
        f"payload round trip: {reloaded.response_payload!r}"
    )
    assert reloaded.response_payload["annotations"] == PAYLOAD["annotations"], (
        "nested mappings and lists must survive JSONB unflattened"
    )
    assert reloaded.response_payload["notes"] == PAYLOAD["notes"], (
        "a list of strings must round trip as a list, not a scalar"
    )


@pytest.mark.asyncio
async def test_timestamps_round_trip_as_timezone_aware_instants(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Timestamps keep their exact instant and their UTC offset."""
    committed = await _commit_run_and_checkpoint(session_factory)
    responded_at = NOW + dt.timedelta(minutes=1)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.respond_to_checkpoint(
            committed.checkpoint_id,
            response=CheckpointResponse(
                action=CheckpointAction.APPROVE,
                payload={},
                responded_at=responded_at,
                responded_by="reviewer@example.com",
            ),
        )
        await uow.commit()

    reloaded = await _read_fresh(session_factory, committed.checkpoint_id)

    assert reloaded is not None, "the committed checkpoint must be readable"
    assert reloaded.created_at == NOW, f"created_at: {reloaded.created_at!r}"
    assert reloaded.created_at.tzinfo is not None, "created_at must be aware"
    assert reloaded.responded_at == responded_at, (
        f"responded_at: {reloaded.responded_at!r}"
    )
    assert reloaded.responded_at is not None, (
        "a responded checkpoint must record its resolution instant"
    )
    assert reloaded.responded_at.tzinfo is not None, "responded_at must be aware"


@pytest.mark.asyncio
async def test_uncommitted_response_does_not_persist(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A unit of work that exits without commit leaves the checkpoint created.

    The warning is captured by patching the unit of work's structured-event
    emitter rather than with ``caplog``: ``get_logger`` returns a femtologging
    logger, whose records never reach a stdlib handler, so ``caplog`` observes
    nothing regardless of whether the event fires.
    """
    committed = await _commit_run_and_checkpoint(session_factory)
    events: list[tuple[str, str, dict[str, object]]] = []

    def record_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    monkeypatch.setattr(uow, "_log_event", record_event)

    async with SqlAlchemyUnitOfWork(session_factory) as uow_instance:
        await uow_instance.generation_runs.respond_to_checkpoint(
            committed.checkpoint_id,
            response=CheckpointResponse(
                action=CheckpointAction.APPROVE,
                payload={"approved": True},
                responded_at=NOW + dt.timedelta(minutes=1),
                responded_by="reviewer@example.com",
            ),
        )

    reloaded = await _read_fresh(session_factory, committed.checkpoint_id)

    assert reloaded is not None, "the committed checkpoint must be readable"
    assert reloaded.status is CheckpointStatus.CREATED, (
        f"without commit the checkpoint must stay created, not {reloaded.status}"
    )
    assert [event[1] for event in events] == [
        "canonical_unit_of_work.closed_with_uncommitted_changes"
    ], "closing with pending state must warn, not discard work silently"
    assert events[0][0] == "warning", "the uncommitted-work event must be a warning"


@pytest.mark.asyncio
async def test_uncommitted_staged_add_warns_before_it_is_discarded(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare staged add is warned about, though nothing has flushed it yet.

    ``test_uncommitted_response_does_not_persist`` cannot cover this shape: its
    write is a core ``UPDATE`` issued through ``Session.execute``, which the
    session write tracker observes directly. Every repository ``add`` in this
    package is instead a bare ``session.add`` with no flush, and the tracker's
    ``before_flush`` listener does not fire until a flush happens -- which, on
    this exit path, never does. Without the session's staged collections in the
    predicate the row would be discarded in silence.
    """
    events: list[tuple[str, str, dict[str, object]]] = []

    def record_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    monkeypatch.setattr(uow, "_log_event", record_event)

    async with SqlAlchemyUnitOfWork(session_factory) as uow_instance:
        await uow_instance.series_profiles.add(
            SeriesProfile(
                id=uuid.uuid7(),
                slug=f"staged-{uuid.uuid7()}",
                title="Staged series profile",
                description=None,
                configuration={},
                guardrails={},
                created_at=NOW,
                updated_at=NOW,
            )
        )

    assert [event[1] for event in events] == [
        "canonical_unit_of_work.closed_with_uncommitted_changes"
    ], "closing with a staged add must warn, not discard work silently"
    assert events[0][0] == "warning", "the uncommitted-work event must be a warning"


@pytest.mark.asyncio
async def test_options_must_be_a_json_array(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A scalar written into options is rejected by the CHECK constraint."""
    committed = await _commit_run_and_checkpoint(session_factory)
    statement = sa.text(
        "UPDATE review_checkpoints SET options = '\"approve\"'::jsonb "
        "WHERE id = :checkpoint_id"
    )

    with pytest.raises(IntegrityError, match="ck_review_checkpoints_options_array"):
        async with session_factory() as session, session.begin():
            await session.execute(statement, {"checkpoint_id": committed.checkpoint_id})
