"""Principal-scoped generation-run idempotency tests."""

import typing as typ

import pytest

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage.test_generation_runs import _factory, make_generation_run

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
    factory = _factory(session_factory)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        first = await uow.generation_runs.create_run(
            make_generation_run(),
            idempotency_key="run-key",
            idempotency_principal_id="principal-a",
        )
        second = await uow.generation_runs.create_run(
            make_generation_run(),
            idempotency_key="run-key",
            idempotency_principal_id="principal-b",
        )
        await uow.commit()

    assert first.id != second.id, "principal scopes must not share a run"
