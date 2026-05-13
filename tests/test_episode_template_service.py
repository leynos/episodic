"""Episode template service tests."""

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical import build_series_brief
from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)
from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateUpdateFields,
    RevisionConflictError,
    SeriesProfileCreateData,
    UpdateEpisodeTemplateRequest,
    create_series_profile,
    list_history,
    update_episode_template,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.fixtures import profile_template_fixtures

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import EpisodeTemplateHistoryEntry


base_profile = profile_template_fixtures.base_profile
base_profile_with_template = profile_template_fixtures.base_profile_with_template
BaseProfileWithTemplateFixture = (
    profile_template_fixtures.BaseProfileWithTemplateFixture
)
seed_cross_series_resolved_binding_brief_scenario = (
    profile_template_fixtures.seed_cross_series_resolved_binding_brief_scenario
)


class TestEpisodeTemplateService:
    """Tests for episode-template service behaviour."""

    @pytest.mark.asyncio
    async def test_update_episode_template_revision_conflict_raises(
        self,
        session_factory: cabc.Callable[[], AsyncSession],
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
                            guardrails={"instruction": "Keep it brief."},
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
        session_factory: cabc.Callable[[], AsyncSession],
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

        assert len(template_history) == 1, "Expected one template history record."
        first_entry = typ.cast("EpisodeTemplateHistoryEntry", template_history[0])
        assert first_entry.revision == 1, "Expected first template revision."
        series_profile = typ.cast("dict[str, object]", brief["series_profile"])
        templates = typ.cast("list[dict[str, object]]", brief["episode_templates"])
        assert series_profile["id"] == str(profile.id), (
            "Expected profile in structured brief."
        )
        assert series_profile["guardrails"] == profile.guardrails, (
            "Expected profile guardrails in structured brief."
        )
        assert any(item["id"] == str(template.id) for item in templates), (
            "Expected template in structured brief."
        )
        matched_template = next(
            (item for item in templates if item["id"] == str(template.id)),
            None,
        )
        assert matched_template is not None, "Expected template in structured brief."
        assert matched_template["guardrails"] == template.guardrails, (
            "Expected template guardrails in structured brief."
        )

    @pytest.mark.asyncio
    async def test_update_episode_template_preserves_existing_guardrails(
        self,
        session_factory: cabc.Callable[[], AsyncSession],
        base_profile_with_template: BaseProfileWithTemplateFixture,
    ) -> None:
        """Partial guardrail updates must merge with persisted template rules."""
        template = base_profile_with_template.template

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            updated_template, updated_revision = await update_episode_template(
                uow,
                request=UpdateEpisodeTemplateRequest(
                    template_id=template.id,
                    expected_revision=base_profile_with_template.template_revision,
                    data=EpisodeTemplateUpdateFields(
                        title="Weekly Template Updated",
                        description="Updated template description",
                        structure={"segments": ["intro", "analysis", "outro"]},
                        guardrails={"instruction": "Close with a sourced takeaway."},
                    ),
                    audit=AuditMetadata(
                        actor="editor@example.com",
                        note="Merge template guardrails",
                    ),
                ),
            )

        assert updated_revision == 2, "Expected template revision to increment to 2."
        assert updated_template.guardrails == {
            "instruction": "Close with a sourced takeaway.",
            "required_sections": ["intro", "news", "outro"],
        }, "Expected partial template guardrail updates to preserve existing keys."

    @pytest.mark.asyncio
    async def test_build_series_brief_rejects_cross_series_reference_documents(
        self,
        session_factory: cabc.Callable[[], AsyncSession],
        base_profile_with_template: BaseProfileWithTemplateFixture,
    ) -> None:
        """Brief generation should reject references owned by another series."""
        profile = base_profile_with_template.profile
        template = base_profile_with_template.template
        now = dt.datetime.now(dt.UTC)

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            foreign_profile, _ = await create_series_profile(
                uow,
                data=SeriesProfileCreateData(
                    slug="foreign-profile",
                    title="Foreign Profile",
                    description="Cross-series owner",
                    configuration={"tone": "direct"},
                    guardrails={},
                ),
                audit=AuditMetadata(
                    actor="author@example.com",
                    note="Create foreign profile",
                ),
            )
            foreign_document = ReferenceDocument(
                id=uuid.uuid4(),
                owner_series_profile_id=foreign_profile.id,
                kind=ReferenceDocumentKind.GUEST_PROFILE,
                lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
                metadata={"name": "Foreign Guest"},
                created_at=now,
                updated_at=now,
            )
            foreign_revision = ReferenceDocumentRevision(
                id=uuid.uuid4(),
                reference_document_id=foreign_document.id,
                content={"bio": "Foreign profile content"},
                content_hash="foreign-hash",
                author="author@example.com",
                change_note="Cross-series revision",
                created_at=now,
            )
            cross_series_binding = ReferenceBinding(
                id=uuid.uuid4(),
                reference_document_revision_id=foreign_revision.id,
                target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
                series_profile_id=None,
                episode_template_id=template.id,
                ingestion_job_id=None,
                effective_from_episode_id=None,
                created_at=now,
            )
            await uow.reference_documents.add(foreign_document)
            await uow.reference_document_revisions.add(foreign_revision)
            await uow.flush()
            await uow.reference_bindings.add(cross_series_binding)
            await uow.commit()

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            with pytest.raises(
                ValueError,
                match="does not belong to requested series profile",
            ):
                await build_series_brief(
                    uow,
                    profile_id=profile.id,
                    template_id=template.id,
                )

    @pytest.mark.asyncio
    async def test_build_series_brief_rejects_cross_series_resolved_bindings(
        self,
        session_factory: cabc.Callable[[], AsyncSession],
        base_profile_with_template: BaseProfileWithTemplateFixture,
    ) -> None:
        """Episode-aware brief generation should reject foreign resolved bindings."""
        profile = base_profile_with_template.profile
        template = base_profile_with_template.template
        now = dt.datetime.now(dt.UTC)

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            episode_id = await seed_cross_series_resolved_binding_brief_scenario(
                uow=uow,
                profile_id=profile.id,
                now=now,
            )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            with pytest.raises(
                ValueError,
                match="does not belong to requested series profile",
            ):
                await build_series_brief(
                    uow,
                    profile_id=profile.id,
                    template_id=template.id,
                    episode_id=episode_id,
                )
