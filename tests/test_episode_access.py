"""Regression tests for the shared episode ownership lookup.

Every episode-scoped resource runs :func:`read_owned_episode` before it exposes
data. These tests pin that the lookup stays a query path: a caller may hold
staged changes while it resolves ownership, and an autoflush there would turn
the check into a write.
"""

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.api.episode_access import read_owned_episode, read_owned_episode_and_run
from episodic.canonical.domain import (
    EpisodeTeiUpdate,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.qa_artefact_mappers import evaluation_to_record
from tests.canonical_storage._qa_artefact_support import (
    create_episode,
    create_ingestion_job,
    make_evaluation,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork

_ACTOR = "principal-a"


async def _episode_with_launcher_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Persist an episode whose launcher run belongs to :data:`_ACTOR`."""
    episode_id = await create_episode(session_factory)
    source_bundle_id = await create_ingestion_job(session_factory, episode_id)
    now = dt.datetime.now(dt.UTC)
    run = GenerationRun(
        id=uuid.uuid7(),
        episode_id=episode_id,
        source_bundle_id=source_bundle_id,
        actor=_ACTOR,
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={},
        configuration={},
        created_at=now,
        updated_at=now,
        started_at=None,
        ended_at=None,
        error_message=None,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="Ownership test bypasses QA.",
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.episodes.update(
            episode_id,
            update=EpisodeTeiUpdate(
                tei_xml="<TEI/>",
                qa_status=QaStatus.SKIPPED,
                last_generation_run_id=run.id,
                expected_revision=1,
                updated_at=now,
            ),
        )
        await uow.commit()
    return episode_id


@pytest.mark.asyncio
async def test_read_owned_episode_does_not_flush_staged_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ownership reads leave the caller's pending rows unflushed.

    The staged evaluation names an episode that does not exist, so flushing it
    would violate the foreign key. An autoflush anywhere in the ownership
    lookup therefore fails the test loudly instead of only costing a write.
    Reaching the run read needs the episode row, so a failure there is what
    proves the boundary covers both queries rather than just the first.
    """
    episode_id = await _episode_with_launcher_run(session_factory)
    pending = evaluation_to_record(
        make_evaluation(uuid.uuid7(), idempotency_key="pending"),
        created_at=dt.datetime.now(dt.UTC),
    )

    session = session_factory()
    uow = SqlAlchemyUnitOfWork(lambda: session)
    async with uow:
        session.add(pending)

        episode = await read_owned_episode(uow, episode_id, _ACTOR)

        assert episode is not None, "the launcher's own episode was not resolved"
        assert pending in session.new, "read_owned_episode flushed staged work"
        assert await session.scalar(sa.text("SELECT 1")) == 1, (
            "the session stopped working after the ownership reads"
        )


@pytest.mark.asyncio
async def test_read_owned_episode_and_run_returns_the_producing_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The producing run is returned only to its own actor."""
    episode_id = await _episode_with_launcher_run(session_factory)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        owned = await read_owned_episode_and_run(uow, episode_id, _ACTOR)
        other_actor = await read_owned_episode_and_run(uow, episode_id, "principal-b")
        anonymous = await read_owned_episode_and_run(uow, episode_id, None)
        missing = await read_owned_episode_and_run(uow, uuid.uuid7(), _ACTOR)

    assert owned is not None, "the owning actor must resolve the episode and run"
    episode, run = owned
    assert episode.id == episode_id, episode.id
    assert run.episode_id == episode_id, run.episode_id
    assert run.actor == _ACTOR, run.actor
    assert other_actor is None, "another actor must not resolve the run"
    assert anonymous is None, "an unauthenticated request must not resolve the run"
    assert missing is None, "an unknown episode must not resolve"


_WRITE_NAMES = frozenset({"add", "update", "create_run", "flush", "commit", "rollback"})
_READ_PREFIX = "get"


class _RecordingProxy:
    """Wrap a collaborator and record every non-read attribute call.

    A repository is only read-only if *every* call it receives is a read, so
    the proxy records anything whose name is a known write or does not start
    with ``get``, not just a fixed allow-list of write methods.
    """

    def __init__(self, inner: object, label: str, calls: list[str]) -> None:
        """Wrap ``inner``, recording attempts as ``label.name``."""
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_label", label)
        object.__setattr__(self, "_calls", calls)

    def __getattr__(self, name: str) -> object:
        """Return a callable that records the call unless it is a read."""
        inner = object.__getattribute__(self, "_inner")
        label = object.__getattribute__(self, "_label")
        calls = object.__getattribute__(self, "_calls")
        target = getattr(inner, name)
        if not callable(target):
            return target
        is_write = name in _WRITE_NAMES or not name.startswith(_READ_PREFIX)

        def call(*args: object, **kwargs: object) -> object:
            """Record a non-read call, then delegate it."""
            if is_write:
                calls.append(f"{label}.{name}")
            return typ.cast("typ.Any", target)(*args, **kwargs)

        return call


class _RecordingReadOnlyUnitOfWork:
    """Unit of work that records any write at the store or session level."""

    def __init__(self, inner: SqlAlchemyUnitOfWork) -> None:
        """Wrap the real unit of work and start the call log."""
        self._inner = inner
        self.calls: list[str] = []

    async def __aenter__(self) -> _RecordingReadOnlyUnitOfWork:
        """Enter the wrapped unit of work."""
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        """Leave the wrapped unit of work."""
        await self._inner.__aexit__(
            exc_type,
            exc,
            typ.cast("typ.Any", traceback),
        )

    def __getattr__(self, name: str) -> object:
        """Delegate an attribute, wrapping stores and recording writes."""
        if name in {"flush", "commit", "rollback", "add"}:
            return self._recorder(name)
        target = getattr(self._inner, name)
        if name in {"episodes", "generation_runs"}:
            return _RecordingProxy(target, name, self.calls)
        return target

    def _recorder(self, name: str) -> object:
        """Return a callable that records an attempted write-side call."""

        def record(*args: object, **kwargs: object) -> object:
            """Record the attempt, then delegate it."""
            _ = (args, kwargs)
            self.calls.append(name)
            return getattr(self._inner, name)(*args, **kwargs)

        return record


@pytest.mark.asyncio
async def test_read_owned_episode_and_run_issues_no_writes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The ownership query performs reads only."""
    episode_id = await _episode_with_launcher_run(session_factory)

    session = session_factory()
    inner = SqlAlchemyUnitOfWork(lambda: session)
    async with inner:
        recording = _RecordingReadOnlyUnitOfWork(inner)
        owned = await read_owned_episode_and_run(
            typ.cast("CanonicalUnitOfWork", recording),
            episode_id,
            _ACTOR,
        )

        assert owned is not None, "the owning actor must resolve the episode and run"
        assert not recording.calls, f"the query wrote: {recording.calls}"
        staged = (len(session.new), len(session.dirty), len(session.deleted))
        assert staged == (0, 0, 0), f"the query staged instances: {staged}"
