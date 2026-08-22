"""Durable terminal-claim contract tests for generation runs."""

import dataclasses as dc
import datetime as dt
import typing as typ

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage._generation_run_support import (
    NOW,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        GenerationRunStatus.SUCCEEDED,
        GenerationRunStatus.FAILED,
        GenerationRunStatus.CANCELLED,
    ],
)
async def test_sql_generation_run_claim_rejects_terminal_status(
    session_factory: async_sessionmaker[AsyncSession],
    status: GenerationRunStatus,
) -> None:
    """The SQL adapter raises rather than claiming any terminal run."""
    run = dc.replace(make_generation_run(), status=status)
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(RunAlreadyTerminal, match="generation run is already"):
            await uow.generation_runs.claim_run_for_execution(
                run.id,
                current_node="draft",
                started_at=NOW,
                lease_expires_at=NOW + dt.timedelta(minutes=5),
            )
