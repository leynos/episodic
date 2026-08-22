"""Generated SQLAlchemy invariants for optimistic TEI revisions."""

import asyncio
import datetime as dt
import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, given, settings

from episodic.canonical.domain import CanonicalEpisode, EpisodeTeiUpdate, GenerationRun
from episodic.canonical.episode_errors import EpisodeRevisionConflictError
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.hashing import sha256_text
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage._generation_run_support import (
    GenerationRunFixture,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:
    type SessionFactory = object

_TEI_BODIES = st.text(alphabet="abc", min_size=1, max_size=8)
_UPDATED_AT = dt.datetime(2026, 7, 24, tzinfo=dt.UTC)


def _tei_xml(body: str) -> str:
    """Build a small valid TEI payload for one generated body."""
    return f"<TEI><text><body><p>{body}</p></body></text></TEI>"


async def _persist_run(
    factory: SessionFactory,
) -> GenerationRun:
    """Persist one run and its episode/source-bundle prerequisites."""
    run = make_generation_run()
    await persist_generation_run_prerequisites(factory, run)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()
    return run


async def _assert_single_winning_update(
    factory: SessionFactory,
    episode_id: uuid.UUID,
    outcomes: tuple[CanonicalEpisode | EpisodeRevisionConflictError, ...],
) -> None:
    """Assert a concurrent optimistic update produced one durable winner."""
    winners: list[CanonicalEpisode] = []
    conflicts: list[EpisodeRevisionConflictError] = []
    for outcome in outcomes:
        match outcome:
            case CanonicalEpisode() as winner:
                winners.append(winner)
            case EpisodeRevisionConflictError() as conflict:
                conflicts.append(conflict)
    assert len(winners) == 1, f"winning updates: {outcomes!r}"
    assert len(conflicts) == 1, f"revision conflicts: {outcomes!r}"

    winner = winners[0]
    async with SqlAlchemyUnitOfWork(factory) as uow:
        stored = await uow.episodes.get(episode_id)
    assert stored is not None, f"episode {episode_id} was not persisted"
    assert stored.tei_revision == 2, f"final revision: {stored.tei_revision}"
    assert stored.tei_xml == winner.tei_xml, (
        f"final TEI {stored.tei_xml!r}, winning TEI {winner.tei_xml!r}"
    )
    assert stored.tei_content_hash == winner.tei_content_hash, (
        "final hash "
        f"{stored.tei_content_hash!r}, winning hash {winner.tei_content_hash!r}"
    )
    assert stored.qa_status is winner.qa_status, (
        f"final QA status {stored.qa_status!r}, winning QA status {winner.qa_status!r}"
    )
    assert stored.last_generation_run_id == winner.last_generation_run_id, (
        "final provenance "
        f"{stored.last_generation_run_id}, winning {winner.last_generation_run_id}"
    )


def _tei_update(
    tei_xml: str,
    run_id: uuid.UUID,
    expected_revision: int,
) -> EpisodeTeiUpdate:
    """Build a deterministic optimistic TEI update command."""
    return EpisodeTeiUpdate(
        tei_xml=tei_xml,
        qa_status=QaStatus.SKIPPED,
        last_generation_run_id=run_id,
        expected_revision=expected_revision,
        updated_at=_UPDATED_AT,
    )


@given(body=_TEI_BODIES)
@settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_sql_tei_updates_matching_revision_increment_once(
    session_factory: SessionFactory,
    body: str,
) -> None:
    """Generated matching revisions persist one TEI revision increment."""
    run = await _persist_run(session_factory)
    tei_xml = _tei_xml(body)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        updated = await uow.episodes.update(
            run.episode_id,
            update=_tei_update(tei_xml, run.id, 1),
        )
        await uow.commit()

    assert updated.tei_revision == 2, f"revision: {updated.tei_revision}"
    assert updated.tei_content_hash == sha256_text(tei_xml), (
        f"content hash: {updated.tei_content_hash!r}"
    )
    assert updated.qa_status is QaStatus.SKIPPED, f"QA status: {updated.qa_status}"
    assert updated.last_generation_run_id == run.id, (
        f"provenance: {updated.last_generation_run_id}"
    )


@given(body=_TEI_BODIES, revision_offset=st.integers(min_value=1, max_value=3))
@settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_sql_tei_updates_stale_revision_preserves_state(
    session_factory: SessionFactory,
    body: str,
    revision_offset: int,
) -> None:
    """Generated stale revisions leave durable TEI state unchanged."""
    run = await _persist_run(session_factory)
    expected_revision = 1 + revision_offset
    tei_xml = _tei_xml(body)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(EpisodeRevisionConflictError) as raised:
            await uow.episodes.update(
                run.episode_id,
                update=_tei_update(tei_xml, run.id, expected_revision),
            )
        await uow.rollback()

    assert raised.value.expected_revision == expected_revision, (
        f"conflict revision: {raised.value.expected_revision}"
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.episodes.get(run.episode_id)
    assert stored is not None, f"episode {run.episode_id} was not persisted"
    assert stored.tei_revision == 1, f"stale update revision: {stored.tei_revision}"
    assert stored.tei_xml == "<TEI/>", f"stale update TEI: {stored.tei_xml!r}"
    assert stored.tei_content_hash == sha256_text("<TEI/>"), (
        f"stale update hash: {stored.tei_content_hash!r}"
    )
    assert stored.qa_status is None, f"stale update QA status: {stored.qa_status}"
    assert stored.last_generation_run_id is None, (
        f"stale update provenance: {stored.last_generation_run_id}"
    )


@given(first_body=_TEI_BODIES, second_body=_TEI_BODIES)
@settings(
    max_examples=4,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_sql_tei_update_race_has_one_winner(
    session_factory: SessionFactory,
    first_body: str,
    second_body: str,
) -> None:
    """Two sessions using one revision precondition admit exactly one update."""
    factory = session_factory
    first_run = make_generation_run()
    second_run = make_generation_run(
        GenerationRunFixture(episode_id=first_run.episode_id)
    )
    await persist_generation_run_prerequisites(factory, first_run, second_run)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(first_run)
        await uow.generation_runs.create_run(second_run)
        await uow.commit()

    barrier = asyncio.Barrier(2)

    async def update(
        run: GenerationRun,
        body: str,
    ) -> CanonicalEpisode | EpisodeRevisionConflictError:
        """Attempt one revision-guarded update from an independent session."""
        async with SqlAlchemyUnitOfWork(factory) as uow:
            await barrier.wait()
            try:
                updated = await uow.episodes.update(
                    run.episode_id,
                    update=_tei_update(_tei_xml(body), run.id, 1),
                )
                await uow.commit()
            except EpisodeRevisionConflictError as exc:
                await uow.rollback()
                return exc
        return updated

    first, second = await asyncio.gather(
        update(first_run, first_body),
        update(second_run, second_body),
    )
    await _assert_single_winning_update(
        factory,
        first_run.episode_id,
        (first, second),
    )
