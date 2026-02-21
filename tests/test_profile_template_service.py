"""Unit and integration tests for profile/template services."""

from __future__ import annotations

import typing as typ

import pytest

from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateData,
    RevisionConflictError,
    SeriesProfileCreateData,
    SeriesProfileData,
    build_series_brief,
    create_episode_template,
    create_series_profile,
    list_episode_template_history,
    list_series_profile_history,
    update_series_profile,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_create_series_profile_creates_initial_history(
    session_factory: typ.Callable[[], AsyncSession],
) -> None:
    """Creating a profile also creates revision 1 history."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        profile, revision = await create_series_profile(
            uow,
            data=SeriesProfileCreateData(
                slug="service-profile",
                title="Service Profile",
                description="Initial profile",
                configuration={"tone": "neutral"},
            ),
            audit=AuditMetadata(
                actor="author@example.com",
                note="Initial version",
            ),
        )

    assert revision == 1, "Expected initial revision to be 1."

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        history = await list_series_profile_history(uow, profile_id=profile.id)

    assert len(history) == 1, "Expected one profile history record."
    assert history[0].revision == 1, "Expected first revision number to be 1."
    assert history[0].actor == "author@example.com", "Expected actor in history."


@pytest.mark.asyncio
async def test_update_series_profile_rejects_revision_conflicts(
    session_factory: typ.Callable[[], AsyncSession],
) -> None:
    """Updating with stale expected revision raises conflict."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        profile, _ = await create_series_profile(
            uow,
            data=SeriesProfileCreateData(
                slug="profile-conflict",
                title="Profile Conflict",
                description="Initial profile",
                configuration={"tone": "neutral"},
            ),
            audit=AuditMetadata(
                actor="author@example.com",
                note="Initial version",
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(RevisionConflictError):
            await update_series_profile(
                uow,
                profile_id=profile.id,
                expected_revision=5,
                data=SeriesProfileData(
                    title="Profile Conflict Updated",
                    description="Changed profile",
                    configuration={"tone": "assertive"},
                ),
                audit=AuditMetadata(
                    actor="editor@example.com",
                    note="Conflict attempt",
                ),
            )


@pytest.mark.asyncio
async def test_create_episode_template_creates_history_and_brief(
    session_factory: typ.Callable[[], AsyncSession],
) -> None:
    """Creating a template records history and is retrievable in brief output."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        profile, _ = await create_series_profile(
            uow,
            data=SeriesProfileCreateData(
                slug="brief-profile",
                title="Brief Profile",
                description="Profile for brief retrieval",
                configuration={"tone": "calm"},
            ),
            audit=AuditMetadata(
                actor="author@example.com",
                note="Initial profile",
            ),
        )
        template, template_revision = await create_episode_template(
            uow,
            series_profile_id=profile.id,
            data=EpisodeTemplateData(
                slug="weekly-template",
                title="Weekly Template",
                description="Template for weekly episodes",
                structure={"segments": ["intro", "news", "outro"]},
                actor="editor@example.com",
                note="Initial template",
            ),
        )

    assert template_revision == 1, "Expected initial template revision to be 1."

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        template_history = await list_episode_template_history(
            uow,
            template_id=template.id,
        )
        brief = await build_series_brief(
            uow,
            profile_id=profile.id,
            template_id=template.id,
        )

    assert len(template_history) == 1, "Expected one template history record."
    assert template_history[0].revision == 1, "Expected first template revision."
    assert brief["series_profile"]["id"] == str(profile.id), (
        "Expected profile in structured brief."
    )
    assert brief["episode_templates"][0]["id"] == str(template.id), (
        "Expected template in structured brief."
    )
