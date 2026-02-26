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

import dataclasses as dc
import itertools
import typing as typ

import pytest
import pytest_asyncio

from episodic.canonical import build_series_brief, build_series_brief_prompt
from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateData,
    EpisodeTemplateUpdateFields,
    RevisionConflictError,
    SeriesProfileCreateData,
    SeriesProfileUpdateFields,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
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
        EpisodeTemplate,
        EpisodeTemplateHistoryEntry,
        SeriesProfile,
        SeriesProfileHistoryEntry,
    )


@dc.dataclass(slots=True)
class BaseProfileFixture:
    """Typed fixture payload for a base series profile."""

    profile: SeriesProfile
    profile_revision: int


@dc.dataclass(slots=True)
class BaseProfileWithTemplateFixture:
    """Typed fixture payload for a base profile and one template."""

    profile: SeriesProfile
    profile_revision: int
    template: EpisodeTemplate
    template_revision: int


@pytest_asyncio.fixture
async def base_profile(
    session_factory: typ.Callable[[], AsyncSession],
) -> BaseProfileFixture:
    """Create a reusable base series profile fixture."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        profile, profile_revision = await create_series_profile(
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
    return BaseProfileFixture(profile=profile, profile_revision=profile_revision)


@pytest_asyncio.fixture
async def base_profile_with_template(
    session_factory: typ.Callable[[], AsyncSession],
    base_profile: BaseProfileFixture,
) -> BaseProfileWithTemplateFixture:
    """Create a reusable base profile fixture with one episode template."""
    profile = base_profile.profile
    profile_revision = base_profile.profile_revision
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        template, template_revision = await create_episode_template(
            uow,
            series_profile_id=profile.id,
            data=EpisodeTemplateData(
                slug="weekly-template",
                title="Weekly Template",
                description="Template for weekly episodes",
                structure={"segments": ["intro", "news", "outro"]},
            ),
            audit=AuditMetadata(
                actor="editor@example.com",
                note="Initial template",
            ),
        )
    return BaseProfileWithTemplateFixture(
        profile=profile,
        profile_revision=profile_revision,
        template=template,
        template_revision=template_revision,
    )


def _reconstruct_prompt_text(
    *,
    static_parts: tuple[str, ...],
    interpolation_values: tuple[str, ...],
) -> str:
    """Rebuild rendered prompt text from its static/interpolation metadata."""
    return "".join(
        f"{part}{value}"
        for part, value in itertools.zip_longest(
            static_parts,
            interpolation_values,
            fillvalue="",
        )
    )


class TestSeriesProfileService:
    """Tests for series-profile service behaviour."""

    @pytest.mark.asyncio
    async def test_create_series_profile_creates_initial_history(
        self,
        session_factory: typ.Callable[[], AsyncSession],
        base_profile: BaseProfileFixture,
    ) -> None:
        """Creating a profile also creates revision 1 history."""
        profile = base_profile.profile
        revision = base_profile.profile_revision

        assert revision == 1, "Expected initial revision to be 1."

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            history = await list_history(
                uow,
                parent_id=profile.id,
                kind="series_profile",
            )
        typed_history = typ.cast("list[SeriesProfileHistoryEntry]", history)
        history = sorted(typed_history, key=lambda entry: entry.revision)

        assert len(history) == 1, "Expected one profile history record."
        first_entry = typ.cast("SeriesProfileHistoryEntry", history[0])
        assert first_entry.revision == 1, "Expected first revision number to be 1."
        assert first_entry.actor == "author@example.com", "Expected actor in history."

    @pytest.mark.asyncio
    async def test_update_series_profile_rejects_revision_conflicts(
        self,
        session_factory: typ.Callable[[], AsyncSession],
        base_profile: BaseProfileFixture,
    ) -> None:
        """Updating with stale expected revision raises conflict."""
        profile = base_profile.profile

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            with pytest.raises(RevisionConflictError, match=r"revision conflict"):
                await update_series_profile(
                    uow,
                    request=UpdateSeriesProfileRequest(
                        profile_id=profile.id,
                        expected_revision=5,
                        data=SeriesProfileUpdateFields(
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
    async def test_update_series_profile_updates_entity_and_appends_history(
        self,
        session_factory: typ.Callable[[], AsyncSession],
        base_profile: BaseProfileFixture,
    ) -> None:
        """Updating with the current revision mutates entity data and history."""
        profile = base_profile.profile
        audit = AuditMetadata(
            actor="reviewer@example.com",
            note="Apply canonical profile update",
        )
        update_payload = SeriesProfileUpdateFields(
            title="Service Profile Updated",
            description="Updated profile description",
            configuration={"tone": "assertive"},
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            updated_profile, updated_revision = await update_series_profile(
                uow,
                request=UpdateSeriesProfileRequest(
                    profile_id=profile.id,
                    expected_revision=1,
                    data=update_payload,
                    audit=audit,
                ),
            )

        assert updated_revision == 2, "Expected profile revision to increment to 2."
        assert updated_profile.title == update_payload.title, (
            "Expected updated profile title."
        )
        assert updated_profile.description == update_payload.description, (
            "Expected updated profile description."
        )
        assert updated_profile.configuration == update_payload.configuration, (
            "Expected updated profile configuration."
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            history = await list_history(
                uow,
                parent_id=profile.id,
                kind="series_profile",
            )
        typed_history = typ.cast("list[SeriesProfileHistoryEntry]", history)
        sorted_history = sorted(typed_history, key=lambda entry: entry.revision)

        assert len(sorted_history) == 2, "Expected two profile history records."
        latest_entry = sorted_history[-1]
        assert latest_entry.revision == 2, "Expected latest revision number to be 2."
        assert latest_entry.actor == audit.actor, "Expected actor in history."


class TestEpisodeTemplateService:
    """Tests for episode-template service behaviour."""

    @pytest.mark.asyncio
    async def test_update_episode_template_revision_conflict_raises(
        self,
        session_factory: typ.Callable[[], AsyncSession],
        base_profile_with_template: BaseProfileWithTemplateFixture,
    ) -> None:
        """Updating a template with a stale revision raises conflict."""
        template = base_profile_with_template.template
        current_revision = base_profile_with_template.template_revision

        stale_revision = current_revision - 1 if current_revision > 1 else 0

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            with pytest.raises(RevisionConflictError, match=r"revision conflict"):
                await update_episode_template(
                    uow,
                    request=UpdateEpisodeTemplateRequest(
                        template_id=template.id,
                        expected_revision=stale_revision,
                        data=EpisodeTemplateUpdateFields(
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
        typed_history = typ.cast("list[EpisodeTemplateHistoryEntry]", history)
        history = sorted(typed_history, key=lambda entry: entry.revision)

        assert len(history) == 1, (
            "Conflicting template update must not create a new history entry."
        )
        first_entry = typ.cast("EpisodeTemplateHistoryEntry", history[0])
        assert first_entry.revision == current_revision, (
            "History revision must remain at the last successful revision."
        )

    @pytest.mark.asyncio
    async def test_create_episode_template_creates_history_and_brief(
        self,
        session_factory: typ.Callable[[], AsyncSession],
        base_profile_with_template: BaseProfileWithTemplateFixture,
    ) -> None:
        """Creating a template records history and is retrievable in brief output."""
        profile = base_profile_with_template.profile
        template = base_profile_with_template.template
        template_revision = base_profile_with_template.template_revision

        assert template_revision == 1, "Expected initial template revision to be 1."

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            template_history = await list_history(
                uow,
                parent_id=template.id,
                kind="episode_template",
            )
            template_history = sorted(
                typ.cast("list[EpisodeTemplateHistoryEntry]", template_history),
                key=lambda entry: entry.revision,
            )
            brief = await build_series_brief(
                uow,
                profile_id=profile.id,
                template_id=template.id,
            )
            rendered_prompt = await build_series_brief_prompt(
                uow,
                profile_id=profile.id,
                template_id=template.id,
            )
            escaped_prompt = await build_series_brief_prompt(
                uow,
                profile_id=profile.id,
                template_id=template.id,
                escape_interpolation=lambda value: f"<<{value}>>",
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
        assert "Series slug: service-profile" in rendered_prompt.text, (
            "Expected prompt to include series slug context."
        )
        assert "Weekly Template" in rendered_prompt.text, (
            "Expected prompt to include template details."
        )
        assert "<<service-profile>>" in escaped_prompt.text, (
            "Expected canonical prompt entrypoint to forward escape callback."
        )
        assert rendered_prompt.interpolations, (
            "Expected prompt rendering to include interpolation metadata."
        )
        assert any(
            item.expression == "series_slug" for item in rendered_prompt.interpolations
        ), "Expected interpolation metadata to include series slug."
        assert any(
            item.expression == "template_count"
            for item in rendered_prompt.interpolations
        ), "Expected interpolation metadata to include template count."
        assert rendered_prompt.static_parts, (
            "Expected prompt rendering to include static template parts."
        )
        assert (
            _reconstruct_prompt_text(
                static_parts=rendered_prompt.static_parts,
                interpolation_values=tuple(
                    item.value for item in rendered_prompt.interpolations
                ),
            )
            == rendered_prompt.text
        ), "Expected static and interpolation metadata to reconstruct text."
