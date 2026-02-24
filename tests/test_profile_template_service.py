"""Profile/template service tests.

Summary
-------
Unit and integration tests for canonical profile/template services.

Purpose
-------
Validate profile and template create/update flows, revision-conflict handling,
history persistence, and structured brief generation.

Usage
-----
Run this module through pytest as part of the canonical service suite.

Example
-------
>>> pytest tests/test_profile_template_service.py -q
"""

from __future__ import annotations

import typing as typ

import pytest

from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateData,
    EpisodeTemplateUpdateFields,
    RevisionConflictError,
    SeriesProfileCreateData,
    SeriesProfileData,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
    build_series_brief,
    create_episode_template,
    create_series_profile,
    list_history,
    update_episode_template,
    update_series_profile,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import (
        EpisodeTemplateHistoryEntry,
        SeriesProfileHistoryEntry,
    )


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
        history = await list_history(
            uow,
            parent_id=profile.id,
            kind="series_profile",
        )
    history = sorted(history, key=lambda entry: entry.revision)

    assert len(history) == 1, "Expected one profile history record."
    first_entry = typ.cast("SeriesProfileHistoryEntry", history[0])
    assert first_entry.revision == 1, "Expected first revision number to be 1."
    assert first_entry.actor == "author@example.com", "Expected actor in history."


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
        with pytest.raises(RevisionConflictError, match=r"revision conflict"):
            await update_series_profile(
                uow,
                request=UpdateSeriesProfileRequest(
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
                ),
            )


@pytest.mark.asyncio
async def test_update_episode_template_revision_conflict_raises(
    session_factory: typ.Callable[[], AsyncSession],
) -> None:
    """Updating a template with a stale revision raises conflict."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        profile, _ = await create_series_profile(
            uow,
            data=SeriesProfileCreateData(
                slug="template-conflict-profile",
                title="Template Conflict Profile",
                description="Profile for template conflict test",
                configuration={"tone": "neutral"},
            ),
            audit=AuditMetadata(
                actor="author@example.com",
                note="Initial profile",
            ),
        )
        template, current_revision = await create_episode_template(
            uow,
            series_profile_id=profile.id,
            data=EpisodeTemplateData(
                slug="template-conflict",
                title="Template Conflict",
                description="Initial template",
                structure={"segments": ["intro"]},
                actor="author@example.com",
                note="Initial template",
            ),
        )

    stale_revision = current_revision - 1 if current_revision > 1 else 0

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(RevisionConflictError, match=r"revision conflict"):
            await update_episode_template(
                uow,
                request=UpdateEpisodeTemplateRequest(
                    template_id=template.id,
                    expected_revision=stale_revision,
                    fields=EpisodeTemplateUpdateFields(
                        title="Stale Template Update",
                        description="Should fail",
                        structure={"segments": ["intro", "outro"]},
                    ),
                    audit=AuditMetadata(
                        actor="editor@example.com",
                        note="Stale update attempt",
                    ),
                ),
            )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        history = await list_history(
            uow,
            parent_id=template.id,
            kind="episode_template",
        )
    history = sorted(history, key=lambda entry: entry.revision)

    assert len(history) == 1, (
        "Conflicting template update must not create a new history entry."
    )
    first_entry = typ.cast("EpisodeTemplateHistoryEntry", history[0])
    assert first_entry.revision == current_revision, (
        "History revision must remain at the last successful revision."
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
        template_history = await list_history(
            uow,
            parent_id=template.id,
            kind="episode_template",
        )
        template_history = sorted(
            template_history,
            key=lambda entry: entry.revision,
        )
        brief = await build_series_brief(
            uow,
            profile_id=profile.id,
            template_id=template.id,
        )

    assert len(template_history) == 1, "Expected one template history record."
    first_entry = typ.cast("EpisodeTemplateHistoryEntry", template_history[0])
    assert first_entry.revision == 1, "Expected first template revision."
    series_profile = typ.cast("dict[str, object]", brief["series_profile"])
    templates = typ.cast("list[dict[str, object]]", brief["episode_templates"])
    assert series_profile["id"] == str(profile.id), (
        "Expected profile in structured brief."
    )
    assert any(item["id"] == str(template.id) for item in templates), (
        "Expected template in structured brief."
    )
