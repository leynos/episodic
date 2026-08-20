"""Generated SQLAlchemy generation-run persistence invariants."""

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ

import hypothesis.strategies as st
import pytest
import sqlalchemy as sa
from hypothesis import given, settings

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate, event_seq
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.generation_run_models import GenerationRunRecord
from episodic.canonical.storage.generation_runs import SqlAlchemyGenerationRunStore
from tests.canonical_storage._generation_run_support import (
    NOW,
    ExecutionClaim,
    GenerationRunFixture,
    claim_run_in_independent_uow,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


_EVENT_KINDS = st.lists(
    st.text(alphabet="abc", min_size=1, max_size=8),
    min_size=1,
    max_size=6,
)

_session_factory: async_sessionmaker[AsyncSession] | None = None


@pytest.fixture(autouse=True)
def _configure_session_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Make the isolated SQL test factory available to generated examples."""
    global _session_factory
    _session_factory = session_factory


def _current_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the function-scoped SQL factory configured for this test."""
    if _session_factory is None:
        msg = "SQL property-test session factory was not configured."
        raise RuntimeError(msg)
    return _session_factory


@dc.dataclass(frozen=True, slots=True)
class _PageRequest:
    """One generated request for run and event pagination."""

    run_count: int
    limit: int
    offset: int
    after_seq: int


async def _recover_expired_lease(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: object,
) -> bool:
    """Apply the documented recovery transition only to an expired running run."""
    parsed_run_id = typ.cast("uuid.UUID", run_id)
    async with session_factory() as session:
        record = await session.scalar(
            sa
            .select(GenerationRunRecord)
            .where(
                GenerationRunRecord.id == parsed_run_id,
                GenerationRunRecord.status == GenerationRunStatus.RUNNING,
                GenerationRunRecord.lease_expires_at.is_not(None),
                GenerationRunRecord.lease_expires_at <= NOW,
            )
            .with_for_update()
        )
        if record is None:
            await session.rollback()
            return False
        store = SqlAlchemyGenerationRunStore(session)
        await store.append_event(
            parsed_run_id,
            kind="run.failed",
            payload={"error_category": "launcher.lease_expired"},
            occurred_at=NOW,
        )
        await store.update_run_status(
            parsed_run_id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.FAILED,
                current_node="failed",
                ended_at=NOW,
                error_message="Generation lease expired; failed manually.",
                error_category="launcher.lease_expired",
            ),
        )
        await session.commit()
    return True


@given(first_kinds=_EVENT_KINDS, second_kinds=_EVENT_KINDS)
@settings(
    max_examples=6,
    deadline=None,
)
@pytest.mark.asyncio
async def test_sql_event_batches_are_gap_free_and_isolated(
    first_kinds: list[str],
    second_kinds: list[str],
) -> None:
    """Persisted event batches keep contiguous sequence spaces per run."""
    factory = _current_session_factory()
    first_run = make_generation_run()
    second_run = make_generation_run()
    await persist_generation_run_prerequisites(factory, first_run, second_run)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(first_run)
        await uow.generation_runs.create_run(second_run)
        for kind in first_kinds:
            await uow.generation_runs.append_event(first_run.id, kind=kind, payload={})
        for kind in second_kinds:
            await uow.generation_runs.append_event(second_run.id, kind=kind, payload={})
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        first_events = await uow.generation_runs.list_events(first_run.id)
        second_events = await uow.generation_runs.list_events(second_run.id)

    assert [event.seq for event in first_events] == list(
        range(1, len(first_kinds) + 1)
    ), first_events
    assert [event.seq for event in second_events] == list(
        range(1, len(second_kinds) + 1)
    ), second_events
    assert [event.kind for event in first_events] == first_kinds, first_events
    assert [event.kind for event in second_events] == second_kinds, second_events


@given(
    request=st.builds(
        _PageRequest,
        run_count=st.integers(min_value=1, max_value=5),
        limit=st.integers(min_value=0, max_value=6),
        offset=st.integers(min_value=0, max_value=6),
        after_seq=st.integers(min_value=0, max_value=6),
    )
)
@settings(
    max_examples=6,
    deadline=None,
)
@pytest.mark.asyncio
async def test_sql_pages_match_creation_and_cursor_reference_slices(
    request: _PageRequest,
) -> None:
    """Run and event pages match their independently calculated durable slices."""
    import uuid

    factory = _current_session_factory()
    episode_id = uuid.uuid7()
    runs = [
        make_generation_run(
            GenerationRunFixture(
                episode_id=episode_id,
                created_at=NOW + dt.timedelta(seconds=index),
            )
        )
        for index in range(request.run_count)
    ]
    await persist_generation_run_prerequisites(factory, *runs)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        for run in runs:
            await uow.generation_runs.create_run(run)
        for index in range(request.run_count):
            await uow.generation_runs.append_event(
                runs[0].id,
                kind=f"event-{index}",
                payload={},
            )
        await uow.commit()

    cursor = min(request.after_seq, request.run_count)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        run_page = await uow.generation_runs.list_runs(
            episode_id,
            limit=request.limit,
            offset=request.offset,
        )
        event_page = await uow.generation_runs.list_events(
            runs[0].id,
            after_seq=event_seq(cursor) if cursor else None,
            limit=request.limit,
            offset=request.offset,
        )

    assert run_page == tuple(runs[request.offset : request.offset + request.limit]), (
        "run page did not match "
        f"offset={request.offset}, limit={request.limit}: {run_page!r}"
    )
    expected_event_indexes = range(
        cursor + request.offset,
        min(request.run_count, cursor + request.offset + request.limit),
    )
    assert [event.kind for event in event_page] == [
        f"event-{index}" for index in expected_event_indexes
    ], event_page


@given(key=st.text(alphabet="abc123", min_size=1, max_size=12))
@settings(
    max_examples=6,
    deadline=None,
)
@pytest.mark.asyncio
async def test_sql_idempotency_keys_are_scoped_to_principals(
    key: str,
) -> None:
    """The same key replays per principal while remaining independent across actors."""
    factory = _current_session_factory()
    first_run = make_generation_run()
    replay_run = make_generation_run()
    other_principal_run = make_generation_run()
    await persist_generation_run_prerequisites(
        factory,
        first_run,
        replay_run,
        other_principal_run,
    )
    async with SqlAlchemyUnitOfWork(factory) as uow:
        first = await uow.generation_runs.create_run(
            first_run,
            idempotency_key=key,
            idempotency_principal_id="principal-a",
        )
        replay = await uow.generation_runs.create_run(
            replay_run,
            idempotency_key=key,
            idempotency_principal_id="principal-a",
        )
        other = await uow.generation_runs.create_run(
            other_principal_run,
            idempotency_key=key,
            idempotency_principal_id="principal-b",
        )
        await uow.commit()

    assert replay.id == first.id, (replay.id, first.id)
    assert other.id == other_principal_run.id, (other.id, other_principal_run.id)
    assert other.id != first.id, (other.id, first.id)


@given(
    first_node=st.text(alphabet="ab", min_size=1, max_size=4),
    second_node=st.text(alphabet="cd", min_size=1, max_size=4),
    lease_offset_seconds=st.integers(min_value=-2, max_value=2),
)
@settings(
    max_examples=5,
    deadline=None,
)
@pytest.mark.asyncio
async def test_sql_claim_races_and_lease_recovery_preserve_one_terminal_path(
    first_node: str,
    second_node: str,
    lease_offset_seconds: int,
) -> None:
    """A pending run has one claimant and recovery acts only on expired leases."""
    factory = _current_session_factory()
    run = make_generation_run()
    await persist_generation_run_prerequisites(factory, run)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    claim_barrier = asyncio.Barrier(2)

    async def claim(node: str) -> GenerationRun | None:
        """Attempt one conditional claim after both sessions are ready."""
        await claim_barrier.wait()
        return await claim_run_in_independent_uow(
            factory,
            run.id,
            ExecutionClaim(
                current_node=node,
                started_at=NOW,
                lease_expires_at=NOW + dt.timedelta(seconds=lease_offset_seconds),
            ),
        )

    first, second = await asyncio.gather(claim(first_node), claim(second_node))
    assert sum(result is not None for result in (first, second)) == 1, (first, second)
    recovered = await _recover_expired_lease(factory, run.id)

    assert recovered is (lease_offset_seconds <= 0), (
        recovered,
        lease_offset_seconds,
    )
    async with SqlAlchemyUnitOfWork(factory) as uow:
        persisted = await uow.generation_runs.get_run(run.id)
        events = await uow.generation_runs.list_events(run.id)
    assert persisted is not None, f"expected persisted run {run.id}"
    if recovered:
        assert persisted.status is GenerationRunStatus.FAILED, persisted.status
        assert [event.kind for event in events] == ["run.failed"], events
    else:
        assert persisted.status is GenerationRunStatus.RUNNING, persisted.status
        assert events == (), events
