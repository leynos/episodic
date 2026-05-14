"""Shared fixtures and helpers for profile/template service tests."""

import dataclasses as dc
import itertools
import typing as typ
import uuid

import pytest
import pytest_asyncio

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
    TeiHeader,
)
from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateData,
    SeriesProfileCreateData,
    create_episode_template,
    create_series_profile,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import datetime as dt

    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import EpisodeTemplate, SeriesProfile
    from episodic.canonical.prompts import RenderedPrompt


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
    session_factory: cabc.Callable[[], AsyncSession],
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
                guardrails={
                    "instruction": "Keep the host voice calm and evidence-led.",
                    "banned_phrases": ["smash that like button"],
                },
            ),
            audit=AuditMetadata(
                actor="author@example.com",
                note="Initial version",
            ),
        )
    return BaseProfileFixture(profile=profile, profile_revision=profile_revision)


@pytest_asyncio.fixture
async def base_profile_with_template(
    session_factory: cabc.Callable[[], AsyncSession],
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
                guardrails={
                    "instruction": "Open with the top story and close with a recap.",
                    "required_sections": ["intro", "news", "outro"],
                },
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


def reconstruct_prompt_text(
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


def assert_rendered_prompt_properties(
    rendered_prompt: object,
    *,
    expected_expressions: list[str],
) -> None:
    """Verify RenderedPrompt contains expected interpolation and static metadata."""
    prompt = typ.cast("RenderedPrompt", rendered_prompt)

    if not prompt.interpolations:
        pytest.fail("Expected prompt rendering to include interpolation metadata.")

    for expression in expected_expressions:
        if not any(item.expression == expression for item in prompt.interpolations):
            pytest.fail(f"Expected interpolation metadata to include {expression}.")

    if not prompt.static_parts:
        pytest.fail("Expected prompt rendering to include static template parts.")

    if (
        reconstruct_prompt_text(
            static_parts=prompt.static_parts,
            interpolation_values=tuple(item.value for item in prompt.interpolations),
        )
        != prompt.text
    ):
        pytest.fail("Expected static and interpolation metadata to reconstruct text.")


def build_brief_test_episode(
    *,
    profile_id: uuid.UUID,
    episode_id: uuid.UUID,
    now: dt.datetime,
) -> tuple[CanonicalEpisode, TeiHeader]:
    """Create an episode/header pair for episode-aware brief tests."""
    episode = CanonicalEpisode(
        id=episode_id,
        series_profile_id=profile_id,
        tei_header_id=uuid.uuid4(),
        title="Episode-aware brief",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    header = TeiHeader(
        id=episode.tei_header_id,
        title=episode.title,
        payload={"file_desc": {"title": episode.title}},
        raw_xml="<teiHeader/>",
        created_at=now,
        updated_at=now,
    )
    return episode, header


def build_cross_series_resolved_binding_fixture(
    *,
    now: dt.datetime,
    foreign_profile_id: uuid.UUID,
    target_profile_id: uuid.UUID,
) -> tuple[ReferenceDocument, ReferenceDocumentRevision, ReferenceBinding]:
    """Create a foreign-owned series binding for episode-aware brief tests."""
    foreign_document = ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=foreign_profile_id,
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
        content_hash="foreign-hash-episode-aware",
        author="author@example.com",
        change_note="Cross-series revision for episode-aware brief",
        created_at=now,
    )
    cross_series_binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=foreign_revision.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=target_profile_id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=now,
    )
    return foreign_document, foreign_revision, cross_series_binding


async def seed_cross_series_resolved_binding_brief_scenario(
    *,
    uow: SqlAlchemyUnitOfWork,
    profile_id: uuid.UUID,
    now: dt.datetime,
) -> uuid.UUID:
    """Persist an episode plus a foreign-owned resolved binding for brief tests."""
    episode_id = uuid.uuid4()
    episode, header = build_brief_test_episode(
        profile_id=profile_id,
        episode_id=episode_id,
        now=now,
    )
    await uow.tei_headers.add(header)
    await uow.flush()
    await uow.episodes.add(episode)

    foreign_profile, _ = await create_series_profile(
        uow,
        data=SeriesProfileCreateData(
            slug="foreign-profile-episode-aware",
            title="Foreign Profile Episode-aware",
            description="Cross-series owner",
            configuration={"tone": "direct"},
            guardrails={},
        ),
        audit=AuditMetadata(
            actor="author@example.com",
            note="Create foreign profile for episode-aware brief",
        ),
    )
    foreign_document, foreign_revision, cross_series_binding = (
        build_cross_series_resolved_binding_fixture(
            now=now,
            foreign_profile_id=foreign_profile.id,
            target_profile_id=profile_id,
        )
    )
    await uow.reference_documents.add(foreign_document)
    await uow.reference_document_revisions.add(foreign_revision)
    await uow.flush()
    await uow.reference_bindings.add(cross_series_binding)
    await uow.commit()
    return episode_id
