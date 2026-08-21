"""Tests for deterministic generation-run storage runtime providers."""

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.generation_run_storage_runtime import (
    GenerationRunStorageRuntime,
)
from tests.canonical_storage._generation_run_support import (
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_generation_run_store_uses_injected_runtime(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Adapter-owned timestamps and event IDs should use UoW runtime seams."""
    run = make_generation_run()
    event_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
    now = dt.datetime(2026, 7, 23, tzinfo=dt.UTC)
    await persist_generation_run_prerequisites(session_factory, run)
    runtime = GenerationRunStorageRuntime(
        clock=lambda: now,
        uuid_factory=lambda: event_id,
    )

    async with SqlAlchemyUnitOfWork(
        session_factory,
        generation_run_runtime=runtime,
    ) as uow:
        await uow.generation_runs.create_run(run)
        updated = await uow.generation_runs.update_run_status(
            run.id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.RUNNING,
                current_node="generate",
                ended_at=None,
            ),
        )
        event = await uow.generation_runs.append_event(
            run.id,
            kind="run.started",
            payload={},
        )
        await uow.commit()

    assert updated.updated_at == now, f"updated timestamp: {updated.updated_at!r}"
    assert event.id == event_id, f"event identifier: {event.id!r}"
    assert event.occurred_at == now, f"event timestamp: {event.occurred_at!r}"
