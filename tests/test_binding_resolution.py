"""Unit tests for reference binding resolution algorithm."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import pytest_asyncio

from episodic.canonical.domain import (
    CanonicalEpisode,
    EpisodeStatus,
    ReferenceBinding,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
    SeriesProfile,
    TeiHeader,
)
from episodic.canonical.ports import CanonicalUnitOfWork
from episodic.canonical.reference_documents.resolution import (
    ResolvedBinding,
    resolve_bindings,
)
from episodic.canonical.storage.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def uow_with_fixtures(session_factory):
    """Provide a UOW with series profile, episodes, reference documents, and revisions."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        now = dt.datetime.now(tz=dt.UTC)

        series = SeriesProfile(
            id=uuid.uuid4(),
            title="Resolution Test Series",
            slug="resolution-test",
            description="Series for resolution tests",
            configuration={},
            guardrails={},
            created_at=now,
            updated_at=now,
        )
        await uow.series_profiles.add(series)

        # Create episodes with predictable ordering via created_at
        episode_early = CanonicalEpisode(
            id=uuid.uuid4(),
            series_profile_id=series.id,
            tei_header_id=uuid.uuid4(),
            title="Early Episode",
            tei_xml="<TEI/>",
            status=EpisodeStatus.DRAFT,
            approval_state="pending",
            created_at=now - dt.timedelta(days=10),
            updated_at=now - dt.timedelta(days=10),
        )
        episode_middle = CanonicalEpisode(
            id=uuid.uuid4(),
            series_profile_id=series.id,
            tei_header_id=uuid.uuid4(),
            title="Middle Episode",
            tei_xml="<TEI/>",
            status=EpisodeStatus.DRAFT,
            approval_state="pending",
            created_at=now - dt.timedelta(days=5),
            updated_at=now - dt.timedelta(days=5),
        )
        episode_late = CanonicalEpisode(
            id=uuid.uuid4(),
            series_profile_id=series.id,
            tei_header_id=uuid.uuid4(),
            title="Late Episode",
            tei_xml="<TEI/>",
            status=EpisodeStatus.DRAFT,
            approval_state="pending",
            created_at=now,
            updated_at=now,
        )

        for ep in [episode_early, episode_middle, episode_late]:
            header = TeiHeader(
                id=ep.tei_header_id,
                title=ep.title,
                payload={"file_desc": {"title": ep.title}},
                raw_xml="<teiHeader/>",
                created_at=ep.created_at,
                updated_at=ep.updated_at,
            )
            await uow.tei_headers.add(header)
            await uow.episodes.add(ep)

        # Create a reference document (style guide)
        doc = ReferenceDocument(
            id=uuid.uuid4(),
            owner_series_profile_id=series.id,
            kind=ReferenceDocumentKind.STYLE_GUIDE,
            lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
            metadata={},
            created_at=now,
            updated_at=now,
            lock_version=1,
        )
        await uow.reference_documents.add(doc)

        # Create revisions
        revision_v1 = ReferenceDocumentRevision(
            id=uuid.uuid4(),
            reference_document_id=doc.id,
            content={"version": "1", "rules": ["rule1"]},
            content_hash="hash-v1",
            author="editor",
            change_note="Initial version",
            created_at=now - dt.timedelta(days=15),
        )
        revision_v2 = ReferenceDocumentRevision(
            id=uuid.uuid4(),
            reference_document_id=doc.id,
            content={"version": "2", "rules": ["rule1", "rule2"]},
            content_hash="hash-v2",
            author="editor",
            change_note="Added rule2",
            created_at=now - dt.timedelta(days=8),
        )
        revision_v3 = ReferenceDocumentRevision(
            id=uuid.uuid4(),
            reference_document_id=doc.id,
            content={"version": "3", "rules": ["rule1", "rule2", "rule3"]},
            content_hash="hash-v3",
            author="editor",
            change_note="Added rule3",
            created_at=now - dt.timedelta(days=2),
        )

        for rev in [revision_v1, revision_v2, revision_v3]:
            await uow.reference_document_revisions.add(rev)

        await uow.commit()

        yield {
            "uow": uow,
            "series": series,
            "episode_early": episode_early,
            "episode_middle": episode_middle,
            "episode_late": episode_late,
            "doc": doc,
            "revision_v1": revision_v1,
            "revision_v2": revision_v2,
            "revision_v3": revision_v3,
            "now": now,
        }


async def test_resolve_bindings_returns_empty_when_no_bindings_exist(uow_with_fixtures):
    """Resolution returns empty list when no bindings exist for series profile."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]

    resolved = await resolve_bindings(uow, series_profile_id=series.id)

    assert resolved == []


async def test_resolve_bindings_returns_default_binding_when_no_episode_context(
    uow_with_fixtures,
):
    """When no episode_id is provided, resolution includes default binding."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    revision_v1 = fixtures["revision_v1"]

    # Create a default binding (effective_from_episode_id = None)
    binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind="series_profile",
        target_series_profile_id=series.id,
        target_episode_template_id=None,
        target_ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=fixtures["now"],
    )
    await uow.reference_bindings.add(binding)
    await uow.commit()

    resolved = await resolve_bindings(uow, series_profile_id=series.id)

    assert len(resolved) == 1
    assert isinstance(resolved[0], ResolvedBinding)
    assert resolved[0].binding.id == binding.id
    assert resolved[0].revision.id == revision_v1.id


async def test_resolve_bindings_selects_episode_specific_binding_over_default(
    uow_with_fixtures,
):
    """Episode-specific binding takes precedence over default when episode_id provided."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    episode_middle = fixtures["episode_middle"]
    revision_v1 = fixtures["revision_v1"]
    revision_v2 = fixtures["revision_v2"]

    # Default binding with v1
    binding_default = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind="series_profile",
        target_series_profile_id=series.id,
        target_episode_template_id=None,
        target_ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=fixtures["now"] - dt.timedelta(days=12),
    )
    # Episode-specific binding with v2, effective from middle episode
    binding_episode = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v2.id,
        target_kind="series_profile",
        target_series_profile_id=series.id,
        target_episode_template_id=None,
        target_ingestion_job_id=None,
        effective_from_episode_id=episode_middle.id,
        created_at=fixtures["now"] - dt.timedelta(days=6),
    )

    await uow.reference_bindings.add(binding_default)
    await uow.reference_bindings.add(binding_episode)
    await uow.commit()

    # Resolve for middle episode
    resolved = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_middle.id
    )

    assert len(resolved) == 1
    assert resolved[0].binding.id == binding_episode.id
    assert resolved[0].revision.id == revision_v2.id


async def test_resolve_bindings_selects_latest_applicable_episode_binding(
    uow_with_fixtures,
):
    """Resolution selects binding with latest effective_from_episode_id that is on or before target."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    episode_early = fixtures["episode_early"]
    episode_middle = fixtures["episode_middle"]
    episode_late = fixtures["episode_late"]
    revision_v1 = fixtures["revision_v1"]
    revision_v2 = fixtures["revision_v2"]
    revision_v3 = fixtures["revision_v3"]

    # Binding v1: effective from early episode
    binding_early = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind="series_profile",
        target_series_profile_id=series.id,
        target_episode_template_id=None,
        target_ingestion_job_id=None,
        effective_from_episode_id=episode_early.id,
        created_at=fixtures["now"] - dt.timedelta(days=11),
    )
    # Binding v2: effective from middle episode
    binding_middle = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v2.id,
        target_kind="series_profile",
        target_series_profile_id=series.id,
        target_episode_template_id=None,
        target_ingestion_job_id=None,
        effective_from_episode_id=episode_middle.id,
        created_at=fixtures["now"] - dt.timedelta(days=6),
    )
    # Binding v3: effective from late episode
    binding_late = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v3.id,
        target_kind="series_profile",
        target_series_profile_id=series.id,
        target_episode_template_id=None,
        target_ingestion_job_id=None,
        effective_from_episode_id=episode_late.id,
        created_at=fixtures["now"] - dt.timedelta(days=1),
    )

    for b in [binding_early, binding_middle, binding_late]:
        await uow.reference_bindings.add(b)
    await uow.commit()

    # Resolve for early episode -> should get binding_early (v1)
    resolved_early = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_early.id
    )
    assert len(resolved_early) == 1
    assert resolved_early[0].binding.id == binding_early.id
    assert resolved_early[0].revision.id == revision_v1.id

    # Resolve for middle episode -> should get binding_middle (v2)
    resolved_middle = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_middle.id
    )
    assert len(resolved_middle) == 1
    assert resolved_middle[0].binding.id == binding_middle.id
    assert resolved_middle[0].revision.id == revision_v2.id

    # Resolve for late episode -> should get binding_late (v3)
    resolved_late = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_late.id
    )
    assert len(resolved_late) == 1
    assert resolved_late[0].binding.id == binding_late.id
    assert resolved_late[0].revision.id == revision_v3.id


async def test_resolve_bindings_excludes_future_episode_bindings(uow_with_fixtures):
    """Bindings with effective_from_episode_id after target episode are excluded."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    episode_early = fixtures["episode_early"]
    episode_late = fixtures["episode_late"]
    revision_v3 = fixtures["revision_v3"]

    # Binding effective from late episode
    binding_late = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v3.id,
        target_kind="series_profile",
        target_series_profile_id=series.id,
        target_episode_template_id=None,
        target_ingestion_job_id=None,
        effective_from_episode_id=episode_late.id,
        created_at=fixtures["now"] - dt.timedelta(days=1),
    )
    await uow.reference_bindings.add(binding_late)
    await uow.commit()

    # Resolve for early episode -> future binding should be excluded
    resolved = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_early.id
    )

    assert resolved == []


async def test_resolve_bindings_falls_back_to_default_when_no_episode_match(
    uow_with_fixtures,
):
    """When no episode-specific binding matches, fall back to default (None effective_from_episode_id)."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    episode_early = fixtures["episode_early"]
    episode_late = fixtures["episode_late"]
    revision_v1 = fixtures["revision_v1"]
    revision_v3 = fixtures["revision_v3"]

    # Default binding with v1
    binding_default = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind="series_profile",
        target_series_profile_id=series.id,
        target_episode_template_id=None,
        target_ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=fixtures["now"] - dt.timedelta(days=12),
    )
    # Episode-specific binding effective from late episode only
    binding_late = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v3.id,
        target_kind="series_profile",
        target_series_profile_id=series.id,
        target_episode_template_id=None,
        target_ingestion_job_id=None,
        effective_from_episode_id=episode_late.id,
        created_at=fixtures["now"] - dt.timedelta(days=1),
    )

    await uow.reference_bindings.add(binding_default)
    await uow.reference_bindings.add(binding_late)
    await uow.commit()

    # Resolve for early episode -> should fall back to default
    resolved = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_early.id
    )

    assert len(resolved) == 1
    assert resolved[0].binding.id == binding_default.id
    assert resolved[0].revision.id == revision_v1.id
