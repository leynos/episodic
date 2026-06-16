"""Storage tests for history repositories.

These tests pin the translation behaviour of the history repositories: a
``(parent_id, revision)`` collision must surface as the domain
``RevisionConflictError`` (chaining the original ``IntegrityError``) rather than
the raw SQLAlchemy exception, while unrelated integrity violations propagate
unchanged. The repositories share the savepoint translation through
``_HistoryRepositoryBase._add_history_entry``, so covering both concrete
repositories pins the wiring for each parent identifier field.
"""

from __future__ import annotations

import typing as typ
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from episodic.canonical.profile_templates.types import RevisionConflictError
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.fixtures.history_entries import (
    build_episode_template,
    build_episode_template_history_entry,
    build_series_profile,
    build_series_profile_history_entry,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_series_profile_history_repository_translates_revision_conflict(
    session_factory: object,
) -> None:
    """Two entries with the same ``(series_profile_id, revision)`` collide.

    The collision must raise ``RevisionConflictError`` with the parent
    series-profile identifier and chain the original ``IntegrityError`` so
    service-layer optimistic-lock handling can report a meaningful error while
    retaining the underlying cause for diagnostics.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    profile = build_series_profile()
    first = build_series_profile_history_entry(profile.id, revision=1)
    duplicate = build_series_profile_history_entry(profile.id, revision=1)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(profile)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profile_history.add(first)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(RevisionConflictError) as exc_info:
            await uow.series_profile_history.add(duplicate)

    assert exc_info.value.entity_id == str(profile.id), (
        "expected RevisionConflictError to carry the parent series profile id"
    )
    assert isinstance(exc_info.value.__cause__, IntegrityError), (
        "expected the original IntegrityError to be chained as the cause"
    )


@pytest.mark.asyncio
async def test_episode_template_history_repository_translates_revision_conflict(
    session_factory: object,
) -> None:
    """Two entries with the same ``(episode_template_id, revision)`` collide.

    Mirrors the series-profile case so both concrete history repositories
    cover the savepoint translation wired through the base class.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    profile = build_series_profile()
    template = build_episode_template(profile.id)
    first = build_episode_template_history_entry(template.id, revision=1)
    duplicate = build_episode_template_history_entry(template.id, revision=1)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(profile)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episode_templates.add(template)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.episode_template_history.add(first)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(RevisionConflictError) as exc_info:
            await uow.episode_template_history.add(duplicate)

    assert exc_info.value.entity_id == str(template.id), (
        "expected RevisionConflictError to carry the parent episode template id"
    )
    assert isinstance(exc_info.value.__cause__, IntegrityError), (
        "expected the original IntegrityError to be chained as the cause"
    )


@pytest.mark.asyncio
async def test_series_profile_history_repository_propagates_unrelated_integrity_error(
    session_factory: object,
) -> None:
    """A missing-parent foreign-key violation propagates as raw ``IntegrityError``.

    Only revision-uniqueness collisions are translated; an entry whose parent
    series profile does not exist must surface the underlying schema error so
    callers can diagnose it rather than mistaking it for a revision conflict.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    orphan_entry = build_series_profile_history_entry(uuid.uuid4(), revision=1)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(IntegrityError):
            await uow.series_profile_history.add(orphan_entry)


@pytest.mark.asyncio
async def test_episode_template_history_repository_propagates_unrelated_integrity_error(
    session_factory: object,
) -> None:
    """A missing-parent foreign-key violation propagates as raw ``IntegrityError``.

    Mirrors the series-profile propagation case for the episode-template
    history repository so both concrete repositories pin the same contract.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    orphan_entry = build_episode_template_history_entry(uuid.uuid4(), revision=1)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(IntegrityError):
            await uow.episode_template_history.add(orphan_entry)
