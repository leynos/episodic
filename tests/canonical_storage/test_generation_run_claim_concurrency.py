"""Two-connection claim races against a real PostgreSQL server (INV-9).

py-pglite serves a single connection, so a competing claim cannot be expressed
there. These tests run only when ``EPISODIC_TEST_POSTGRES_DSN`` names a
disposable server; see :mod:`tests.canonical_storage._postgres_claim_race_support`
for the database isolation and synchronization they rely on.

Each test holds one transaction open and starts a competing claim on a second
connection. The test waits until PostgreSQL reports the competitor as blocked
on the row lock, then releases the holder, so the outcome is synchronized on
the database rather than on a sleep.
"""

import asyncio
import os
import typing as typ
import uuid

import pytest
import sqlalchemy.exc as sa_exc
from sqlalchemy.engine import make_url

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage._postgres_claim_race_support import (
    DSN_VARIABLE,
    CommitGate,
    claim,
    claim_token,
    competing_claim,
    create_database,
    database_exists,
    database_name,
    drop_database,
    hold_failure_and_claim,
    isolated_database,
    load_events,
    pending_run,
    postgres_factory,
    require_dsn,
    wait_for_claim_lock_wait,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["postgres_factory"]


@pytest.mark.asyncio
async def test_a_committed_claim_beats_the_blocked_competitor(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A competitor waits on the row lock and loses once the claim commits."""
    run = await pending_run(postgres_factory)
    winner_proof = uuid.uuid4()
    loser_proof = uuid.uuid4()
    claimed = asyncio.Event()
    release = asyncio.Event()

    async def hold_claim() -> bool:
        """Claim, hold the transaction open, then commit when released."""
        async with SqlAlchemyUnitOfWork(postgres_factory) as uow:
            outcome = await uow.generation_runs.claim_run_for_execution(
                run.id,
                claim(winner_proof),
            )
            claimed.set()
            await release.wait()
            await uow.commit()
        return outcome is not None

    holder = asyncio.create_task(hold_claim())
    await asyncio.wait_for(claimed.wait(), timeout=10)
    competitor = asyncio.create_task(
        competing_claim(postgres_factory, run.id, loser_proof),
    )
    await wait_for_claim_lock_wait(postgres_factory)

    release.set()
    assert await asyncio.wait_for(holder, timeout=10) is True, (
        "the holding claim must commit"
    )
    assert await asyncio.wait_for(competitor, timeout=10) is False, (
        "the competitor must lose after the claim commits"
    )

    stored_proof = await claim_token(postgres_factory, run.id)
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
    run = await pending_run(postgres_factory)
    abandoned_proof = uuid.uuid4()
    winner_proof = uuid.uuid4()
    claimed = asyncio.Event()
    release = asyncio.Event()

    async def hold_claim() -> None:
        """Claim, hold the transaction open, then roll back when released."""
        async with SqlAlchemyUnitOfWork(postgres_factory) as uow:
            await uow.generation_runs.claim_run_for_execution(
                run.id,
                claim(abandoned_proof),
            )
            claimed.set()
            await release.wait()
            await uow.rollback()

    holder = asyncio.create_task(hold_claim())
    await asyncio.wait_for(claimed.wait(), timeout=10)
    competitor = asyncio.create_task(
        competing_claim(postgres_factory, run.id, winner_proof),
    )
    await wait_for_claim_lock_wait(postgres_factory)

    release.set()
    await asyncio.wait_for(holder, timeout=10)
    assert await asyncio.wait_for(competitor, timeout=10) is True, (
        "the competitor must win after the rollback"
    )

    stored_proof = await claim_token(postgres_factory, run.id)
    assert stored_proof == winner_proof, "the competitor's proof must be durable"


@pytest.mark.asyncio
async def test_the_failure_transaction_blocks_the_competing_claim(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A competitor cannot win while a failure write holds its transaction."""
    run = await pending_run(postgres_factory)
    failure_proof = uuid.uuid4()
    competitor_proof = uuid.uuid4()
    gate = CommitGate()

    writer = asyncio.create_task(
        hold_failure_and_claim(postgres_factory, gate, run.id, failure_proof),
    )
    await asyncio.wait_for(gate.entered.wait(), timeout=10)
    competitor = asyncio.create_task(
        competing_claim(postgres_factory, run.id, competitor_proof),
    )
    await wait_for_claim_lock_wait(postgres_factory)

    gate.release.set()
    assert await asyncio.wait_for(writer, timeout=10) is True, (
        "the failure write must commit"
    )
    with pytest.raises(RunAlreadyTerminal):
        await asyncio.wait_for(competitor, timeout=10)

    run_after, kinds = await load_events(postgres_factory, run.id)
    assert kinds == ["run.failed"], kinds
    assert run_after.status is GenerationRunStatus.FAILED, run_after.status
    stored_proof = await claim_token(postgres_factory, run.id)
    assert stored_proof == failure_proof, "the failure's proof must stay durable"


def test_database_names_are_unique_per_invocation_and_worker() -> None:
    """Invocations and workers cannot select each other's database."""
    names = {
        database_name("episodic_test", worker="gw0", pid=1, nonce="aaaa"),
        database_name("episodic_test", worker="gw0", pid=1, nonce="bbbb"),
        database_name("episodic_test", worker="gw1", pid=1, nonce="aaaa"),
        database_name("episodic_test", worker="gw0", pid=2, nonce="aaaa"),
    }
    assert len(names) == 4, names
    assert all(len(name.encode("utf-8")) <= 63 for name in names), names


def test_database_names_respect_the_byte_limit() -> None:
    """A multibyte base keeps the full suffix inside 63 bytes."""
    name = database_name(
        "episódio_teste_aprovação_" * 4,
        worker="gw0",
        pid=12345,
        nonce="a1b2c3d4",
    )
    assert len(name.encode("utf-8")) <= 63, name
    assert name.endswith("_wgw0_12345_a1b2c3d4"), name


def test_a_non_test_dsn_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every server-backed entry point rejects a non-_test base database."""
    monkeypatch.setenv(
        DSN_VARIABLE,
        "postgresql+psycopg://user:secret@127.0.0.1:5432/episodic",
    )
    with pytest.raises(pytest.fail.Exception, match="_test"):
        require_dsn()


@pytest.mark.asyncio
async def test_creation_never_drops_a_pre_existing_database() -> None:
    """A repeated create is refused, and the existing database survives."""
    dsn = require_dsn()
    name = database_name(
        str(make_url(dsn).database),
        worker=os.environ.get("PYTEST_XDIST_WORKER", "main"),
        pid=os.getpid(),
        nonce=uuid.uuid4().hex[:8],
    )
    await create_database(dsn, name)
    try:
        with pytest.raises(sa_exc.DBAPIError, match="already exists"):
            await create_database(dsn, name)
        assert await database_exists(dsn, name) is True, "the database must survive"
    finally:
        await drop_database(dsn, name)


@pytest.mark.asyncio
async def test_concurrent_invocations_keep_separate_databases() -> None:
    """Two invocations at once own distinct databases until their teardown."""
    dsn = require_dsn()

    async def invocation() -> str:
        """Create, migrate and drop one database, returning its name."""
        async with isolated_database(dsn) as (name, _factory):
            await asyncio.sleep(0.1)
            assert await database_exists(dsn, name) is True, name
            return name

    first, second = await asyncio.gather(invocation(), invocation())
    assert first != second, (first, second)
    assert await database_exists(dsn, first) is False, first
    assert await database_exists(dsn, second) is False, second
