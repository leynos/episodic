"""Series profile service tests."""

import typing as typ

import pytest

from episodic.canonical.profile_templates import (
    AuditMetadata,
    RevisionConflictError,
    SeriesProfileUpdateFields,
    UpdateSeriesProfileRequest,
    list_history,
    update_series_profile,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.fixtures import profile_template_fixtures

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import SeriesProfileHistoryEntry


base_profile = profile_template_fixtures.base_profile


class TestSeriesProfileService:
    """Tests for series-profile service behaviour."""

    @pytest.mark.asyncio
    async def test_create_series_profile_creates_initial_history(
        self,
        session_factory: typ.Callable[[], AsyncSession],
        base_profile: profile_template_fixtures.BaseProfileFixture,
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
        base_profile: profile_template_fixtures.BaseProfileFixture,
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
                            guardrails={"instruction": "Stay factual."},
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
        base_profile: profile_template_fixtures.BaseProfileFixture,
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
            guardrails={
                "instruction": "Stay precise and cite uncertainty explicitly.",
            },
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
        assert updated_profile.guardrails == {
            "instruction": "Stay precise and cite uncertainty explicitly.",
            "banned_phrases": ["smash that like button"],
        }, "Expected partial profile guardrail updates to preserve existing keys."

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            persisted_profile = await uow.series_profiles.get(profile.id)

        assert persisted_profile is not None, "Expected updated profile to persist."
        assert persisted_profile.guardrails == updated_profile.guardrails, (
            "Expected persisted profile guardrails to match the merged update."
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
