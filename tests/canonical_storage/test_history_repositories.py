"""Storage tests for history repositories.

These tests pin the translation behaviour of the history repositories: a
``(parent_id, revision)`` collision must surface as the domain
``RevisionConflictError`` rather than the underlying SQLAlchemy
``IntegrityError``. The repositories share the savepoint translation through
``_HistoryRepositoryBase._add_history_entry``, so covering both concrete
repositories pins the wiring for each parent identifier field.
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import (
    EpisodeTemplate,
    EpisodeTemplateHistoryEntry,
    SeriesProfile,
    SeriesProfileHistoryEntry,
)
from episodic.canonical.profile_templates.types import RevisionConflictError
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _series_profile(profile_id: uuid.UUID) -> SeriesProfile:
    """Return a minimal series profile fixture for history-conflict tests."""
    now = _now()
    return SeriesProfile(
        id=profile_id,
        slug=f"history-conflict-{profile_id}",
        title="History Conflict",
        description=None,
        configuration={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )


def _episode_template(
    template_id: uuid.UUID,
    series_profile_id: uuid.UUID,
) -> EpisodeTemplate:
    """Return a minimal episode template fixture for history-conflict tests."""
    now = _now()
    return EpisodeTemplate(
        id=template_id,
        series_profile_id=series_profile_id,
        slug=f"history-conflict-template-{template_id}",
        title="History Conflict Template",
        description=None,
        structure={"sections": []},
        guardrails={},
        created_at=now,
        updated_at=now,
    )


def _series_history_entry(
    profile_id: uuid.UUID,
    *,
    revision: int,
) -> SeriesProfileHistoryEntry:
    """Build a series-profile history entry at ``revision``."""
    return SeriesProfileHistoryEntry(
        id=uuid.uuid4(),
        series_profile_id=profile_id,
        revision=revision,
        actor="actor@example.com",
        note=f"Revision {revision}",
        snapshot={"revision": revision},
        created_at=_now(),
    )


def _template_history_entry(
    template_id: uuid.UUID,
    *,
    revision: int,
) -> EpisodeTemplateHistoryEntry:
    """Build an episode-template history entry at ``revision``."""
    return EpisodeTemplateHistoryEntry(
        id=uuid.uuid4(),
        episode_template_id=template_id,
        revision=revision,
        actor="actor@example.com",
        note=f"Revision {revision}",
        snapshot={"revision": revision},
        created_at=_now(),
    )


@pytest.mark.asyncio
async def test_series_profile_history_repository_translates_revision_conflict(
    session_factory: object,
) -> None:
    """Two entries with the same ``(series_profile_id, revision)`` collide.

    The collision must raise ``RevisionConflictError`` with the parent
    series-profile identifier so service-layer optimistic-lock handling can
    report a meaningful error without touching SQLAlchemy types.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    profile = _series_profile(uuid.uuid4())
    first = _series_history_entry(profile.id, revision=1)
    duplicate = _series_history_entry(profile.id, revision=1)

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


@pytest.mark.asyncio
async def test_episode_template_history_repository_translates_revision_conflict(
    session_factory: object,
) -> None:
    """Two entries with the same ``(episode_template_id, revision)`` collide.

    Mirrors the series-profile case so both concrete history repositories
    cover the savepoint translation wired through the base class.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    profile = _series_profile(uuid.uuid4())
    template = _episode_template(uuid.uuid4(), profile.id)
    first = _template_history_entry(template.id, revision=1)
    duplicate = _template_history_entry(template.id, revision=1)

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
