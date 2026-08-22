"""Principal-scoped generation-run idempotency tests."""

import typing as typ

import pytest

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from episodic.canonical.storage import GenerationRunRecord, SqlAlchemyUnitOfWork
from tests.canonical_storage._generation_run_support import (
    count_records,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_in_memory_generation_runs_scope_keys_to_principals() -> None:
    """Distinct principals may use the same generation-run idempotency key."""
    store = InMemoryGenerationRunStore()
    first = await store.create_run(
        make_generation_run(),
        idempotency_key="run-key",
        idempotency_principal_id="principal-a",
    )
    second = await store.create_run(
        make_generation_run(),
        idempotency_key="run-key",
        idempotency_principal_id="principal-b",
    )

    assert first.id != second.id, "principal scopes must not share a run"


@pytest.mark.asyncio
async def test_in_memory_generation_runs_reject_negative_event_limit() -> None:
    """Event pagination limits must be non-negative."""
    store = InMemoryGenerationRunStore()
    run = await store.create_run(make_generation_run())

    with pytest.raises(ValueError, match="limit"):
        await store.list_events(run.id, limit=-1)


@pytest.mark.asyncio
async def test_sql_generation_runs_scope_keys_to_principals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The SQL adapter persists a distinct run for each principal scope."""
    first_request = make_generation_run()
    second_request = make_generation_run()
    replay_request = make_generation_run()
    await persist_generation_run_prerequisites(
        session_factory,
        first_request,
        second_request,
        replay_request,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        first = await uow.generation_runs.create_run(
            first_request,
            idempotency_key="run-key",
            idempotency_principal_id="principal-a",
        )
        second = await uow.generation_runs.create_run(
            second_request,
            idempotency_key="run-key",
            idempotency_principal_id="principal-b",
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        replayed = await uow.generation_runs.create_run(
            replay_request,
            idempotency_key="run-key",
            idempotency_principal_id="principal-a",
        )
        await uow.commit()

    assert first.id != second.id, "principal scopes must not share a run"
    assert replayed == first, "same-principal replay must return the first run"
    record_count = await count_records(session_factory, GenerationRunRecord)
    assert record_count == 2, f"expected two generation runs, got {record_count}"
