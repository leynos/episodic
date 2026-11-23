"""Real-PostgreSQL support for two-connection generation-run claim races.

py-pglite serves a single connection, so a competing claim cannot be expressed
there. These helpers run the race against a server named by
``EPISODIC_TEST_POSTGRES_DSN``. The DSN must select the psycopg async driver
and its base database must end in ``_test``; the user must be allowed to create
and drop databases, because each xdist worker gets its own
``<database>_w<worker>`` database that the fixture creates, migrates and drops.
"""

import asyncio
import dataclasses as dc
import datetime as dt
import functools
import os
import types
import typing as typ
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from episodic.canonical.generation_claim import ExecutionClaim
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.alembic_helpers import apply_migrations
from episodic.generation.launcher_claim import GenerationRunClaimer
from episodic.generation.launcher_failure import GenerationRunFailurePersistence
from episodic.generation.launcher_persistence import PersistenceContext
from episodic.generation.launcher_support import Failure, RunClaim
from tests.canonical_storage._generation_run_support import (
    GenerationRunFixture,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.engine import URL
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
    )

    from episodic.canonical.domain import GenerationRun

_DSN_VARIABLE = "EPISODIC_TEST_POSTGRES_DSN"
_TEST_SUFFIX = "_test"
_LOCK_POLL_SECONDS = 0.05
_LOCK_POLL_LIMIT = 200
_IDENTIFIER_LIMIT = 63


def _worker_database_name(base_database: str) -> str:
    """Return this xdist worker's database name."""
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    suffix = f"_w{worker}"
    return f"{base_database[: _IDENTIFIER_LIMIT - len(suffix)]}{suffix}"


def _render(url: URL) -> str:
    """Render a URL with its password intact."""
    return url.render_as_string(hide_password=False)


def _admin_engine(dsn: str) -> AsyncEngine:
    """Open an autocommit engine on the server's maintenance database."""
    from sqlalchemy.ext.asyncio import create_async_engine

    admin = make_url(dsn).set(database="postgres")
    return create_async_engine(_render(admin), isolation_level="AUTOCOMMIT")


async def _replace_database(dsn: str, name: str) -> None:
    """Drop a leftover worker database and create it afresh."""
    engine = _admin_engine(dsn)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            )
            await connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def _drop_database(dsn: str, name: str) -> None:
    """Drop the worker database at teardown."""
    engine = _admin_engine(dsn)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            )
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def postgres_factory() -> cabc.AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a session factory over this worker's own migrated database."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    dsn = os.environ.get(_DSN_VARIABLE)
    if not dsn:
        pytest.skip(f"set {_DSN_VARIABLE} to run real-PostgreSQL claim races")
    base_database = str(make_url(dsn).database)
    if not base_database.endswith(_TEST_SUFFIX):
        pytest.fail(
            f"{_DSN_VARIABLE} must name a database ending in {_TEST_SUFFIX!r}",
            pytrace=False,
        )
    name = _worker_database_name(base_database)
    await _replace_database(dsn, name)
    engine = create_async_engine(_render(make_url(dsn).set(database=name)))
    try:
        await apply_migrations(engine)
        yield async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    finally:
        await engine.dispose()
        await _drop_database(dsn, name)


async def pending_run(
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


def claim(proof: uuid.UUID) -> ExecutionClaim:
    """Build the execution claim a competing launcher would send."""
    now = dt.datetime.now(dt.UTC)
    return ExecutionClaim(
        current_node=None,
        started_at=now,
        lease_expires_at=None,
        claim_token=proof,
    )


async def claim_token(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> uuid.UUID | None:
    """Read the durable claim proof for a run."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        return await uow.generation_runs.claim_token_for(run_id)


async def load_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> tuple[GenerationRun, list[str]]:
    """Load a run and the kinds of its events."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)
    if run is None:
        msg = f"run {run_id} was not persisted"
        raise AssertionError(msg)
    return run, [event.kind for event in events]


async def wait_for_claim_lock_wait(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Block until a backend is waiting for a generation-run lock.

    ``pg_stat_activity`` is the synchronization point: it reports a backend
    only after that backend reached the server and was refused the lock, so
    the test does not have to guess with a sleep.

    Raises
    ------
    AssertionError
        If no backend reports a lock wait within the poll budget.
    """
    statement = sa.text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() "
        "AND wait_event_type = 'Lock' "
        "AND query LIKE '%generation_runs%'"
    )
    for _ in range(_LOCK_POLL_LIMIT):
        async with session_factory() as probe:
            waiting = await probe.scalar(statement)
        if waiting and int(waiting) > 0:
            return
        await asyncio.sleep(_LOCK_POLL_SECONDS)
    msg = "no competing claim reached a lock wait"
    raise AssertionError(msg)


@dc.dataclass(slots=True)
class CommitGate:
    """Control a unit of work's commit so a transaction can be held open."""

    entered: asyncio.Event = dc.field(default_factory=asyncio.Event)
    release: asyncio.Event = dc.field(default_factory=asyncio.Event)


class GatedCommitUnitOfWork(SqlAlchemyUnitOfWork):
    """Unit of work whose commit waits for the test to release it."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gate: CommitGate,
    ) -> None:
        """Open the real unit of work with the supplied commit gate."""
        super().__init__(session_factory)
        self._gate = gate

    async def commit(self) -> None:
        """Hold the transaction open, then commit when released."""
        self._gate.entered.set()
        await self._gate.release.wait()
        await super().commit()


def _claimer(
    uow_factory: cabc.Callable[[], SqlAlchemyUnitOfWork],
) -> GenerationRunClaimer:
    """Build a claimer whose only used collaborator is ``uow_factory``."""
    runtime = types.SimpleNamespace(
        uow_factory=uow_factory,
        clock=lambda: dt.datetime.now(dt.UTC),
    )
    return GenerationRunClaimer(typ.cast("typ.Any", runtime))


async def hold_failure_and_claim(
    session_factory: async_sessionmaker[AsyncSession],
    gate: CommitGate,
    run_id: uuid.UUID,
    proof: uuid.UUID,
) -> bool:
    """Record a failure that holds its transaction until the gate releases."""
    uow_class = functools.partial(GatedCommitUnitOfWork, session_factory, gate)
    claimer = _claimer(uow_class)
    failures = GenerationRunFailurePersistence(
        runtime=PersistenceContext(
            uow_factory=uow_class,
            clock=lambda: dt.datetime.now(dt.UTC),
        ),
        claim_for_failure=claimer.claim_for_failure,
    )
    result = await failures.record_failure(
        run_id,
        Failure("held failure", "unexpected"),
        claim=RunClaim(proof=proof),
    )
    return result.written


async def competing_claim(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    proof: uuid.UUID,
) -> bool:
    """Attempt the same claim from a second connection."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        outcome = await uow.generation_runs.claim_run_for_execution(
            run_id,
            claim(proof),
        )
        await uow.commit()
    return outcome is not None
