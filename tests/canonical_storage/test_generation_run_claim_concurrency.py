"""Two-connection claim races against a real PostgreSQL server (INV-9).

py-pglite serves a single connection, so a competing claim cannot be expressed
there. These tests run only when ``EPISODIC_TEST_POSTGRES_DSN`` names a
disposable PostgreSQL database whose name ends in ``_test``; the fixture drops
and recreates ``public`` before migrating, so it refuses any other database.
The DSN must select the psycopg async driver, for example
``postgresql+psycopg://user:secret@127.0.0.1:5432/episodic_test``.
"""

import asyncio
import dataclasses as dc
import datetime as dt
import os
import typing as typ
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_claim import ExecutionClaim
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.alembic_helpers import apply_migrations
from tests.canonical_storage._generation_run_support import (
    GenerationRunFixture,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DSN_VARIABLE = "EPISODIC_TEST_POSTGRES_DSN"
_TEST_SUFFIX = "_test"


async def _pending_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> GenerationRun:
    """Persist the prerequisites and one pending QA-gated run."""
    run = dc.replace(
        make_generation_run(GenerationRunFixture(run_id=uuid.uuid7())),
        quality_mode=QualityMode.QA_GATED,
        qa_status=QaStatus.PENDING,
        skip_qa_rationale=None,
    )
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.generation_runs.create_run(run)
        await uow.commit()
    return stored


def _claim(proof: uuid.UUID) -> ExecutionClaim:
    """Build the execution claim a competing launcher would send."""
    now = dt.datetime.now(dt.UTC)
    return ExecutionClaim(
        current_node=None,
        started_at=now,
        lease_expires_at=None,
        claim_token=proof,
    )


async def _claim_token(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> uuid.UUID | None:
    """Read the durable claim proof for a run."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        return await uow.generation_runs.claim_token_for(run_id)


@pytest_asyncio.fixture
async def postgres_factory() -> cabc.AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Migrate a disposable PostgreSQL database and yield its session factory."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    dsn = os.environ.get(_DSN_VARIABLE)
    if not dsn:
        pytest.skip(f"set {_DSN_VARIABLE} to run real-PostgreSQL claim races")
    database = make_url(dsn).database
    if database is None or not database.endswith(_TEST_SUFFIX):
        pytest.fail(
            f"{_DSN_VARIABLE} must name a database ending in {_TEST_SUFFIX!r}",
            pytrace=False,
        )
    engine = create_async_engine(dsn)
    async with engine.begin() as connection:
        await connection.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(sa.text("CREATE SCHEMA public"))
    await apply_migrations(engine)
    try:
        yield async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_committed_claim_beats_the_blocked_competitor(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A competitor waits on the row lock and loses once the claim commits."""
    run = await _pending_run(postgres_factory)
    winner_proof = uuid.uuid4()
    loser_proof = uuid.uuid4()
    claimed = asyncio.Event()
    release = asyncio.Event()

    async def hold_claim() -> bool:
        """Claim, hold the transaction open, then commit when released."""
        async with SqlAlchemyUnitOfWork(postgres_factory) as uow:
            outcome = await uow.generation_runs.claim_run_for_execution(
                run.id,
                _claim(winner_proof),
            )
            claimed.set()
            await release.wait()
            await uow.commit()
        return outcome is not None

    async def compete() -> bool:
        """Attempt the same claim from a second connection."""
        async with SqlAlchemyUnitOfWork(postgres_factory) as uow:
            outcome = await uow.generation_runs.claim_run_for_execution(
                run.id,
                _claim(loser_proof),
            )
        return outcome is not None

    holder = asyncio.create_task(hold_claim())
    await asyncio.wait_for(claimed.wait(), timeout=10)
    competitor = asyncio.create_task(compete())
    await asyncio.sleep(0.5)
    assert not competitor.done(), "the competitor must block on the row lock"

    release.set()
    assert await asyncio.wait_for(holder, timeout=10) is True, (
        "the holding claim must commit"
    )
    assert await asyncio.wait_for(competitor, timeout=10) is False, (
        "the competitor must lose after the claim commits"
    )

    stored_proof = await _claim_token(postgres_factory, run.id)
    assert stored_proof == winner_proof, "the winner's proof must stay durable"
    async with SqlAlchemyUnitOfWork(postgres_factory) as uow:
        stored = await uow.generation_runs.get_run(run.id)
    assert stored is not None, "the claimed run must be readable"
    assert stored.status is GenerationRunStatus.RUNNING, stored.status


@pytest.mark.asyncio
async def test_a_rolled_back_claim_lets_the_competitor_win(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A competitor claims the run once the open transaction rolls back."""
    run = await _pending_run(postgres_factory)
    abandoned_proof = uuid.uuid4()
    winner_proof = uuid.uuid4()
    claimed = asyncio.Event()
    release = asyncio.Event()

    async def hold_claim() -> None:
        """Claim, hold the transaction open, then roll back when released."""
        async with SqlAlchemyUnitOfWork(postgres_factory) as uow:
            await uow.generation_runs.claim_run_for_execution(
                run.id,
                _claim(abandoned_proof),
            )
            claimed.set()
            await release.wait()
            await uow.rollback()

    async def compete() -> bool:
        """Attempt the same claim from a second connection."""
        async with SqlAlchemyUnitOfWork(postgres_factory) as uow:
            outcome = await uow.generation_runs.claim_run_for_execution(
                run.id,
                _claim(winner_proof),
            )
            await uow.commit()
        return outcome is not None

    holder = asyncio.create_task(hold_claim())
    await asyncio.wait_for(claimed.wait(), timeout=10)
    competitor = asyncio.create_task(compete())
    await asyncio.sleep(0.5)
    assert not competitor.done(), "the competitor must block on the row lock"

    release.set()
    await asyncio.wait_for(holder, timeout=10)
    assert await asyncio.wait_for(competitor, timeout=10) is True, (
        "the competitor must win after the rollback"
    )

    stored_proof = await _claim_token(postgres_factory, run.id)
    assert stored_proof == winner_proof, "the competitor's proof must be durable"
