"""Unit tests for reference binding resolution algorithm."""

import datetime as dt
import typing as typ
import uuid

import pytest
import pytest_asyncio

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    EpisodeTemplate,
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
    SeriesProfile,
    TeiHeader,
)
from episodic.canonical.reference_documents.resolution import (
    ResolvedBinding,
    resolve_bindings,
)
from episodic.canonical.storage.uow import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork

pytestmark = pytest.mark.asyncio


def _create_series(now: dt.datetime) -> SeriesProfile:
    """Create and return a series profile for testing."""
    return SeriesProfile(
        id=uuid.uuid4(),
        title="Resolution Test Series",
        slug="resolution-test",
        description="Series for resolution tests",
        configuration={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )


def _create_episodes_with_headers(
    series_id: uuid.UUID, now: dt.datetime
) -> tuple[CanonicalEpisode, CanonicalEpisode, CanonicalEpisode, list[TeiHeader]]:
    """Create three episodes with staggered timestamps and their TEI headers."""
    episode_early = CanonicalEpisode(
        id=uuid.uuid4(),
        series_profile_id=series_id,
        tei_header_id=uuid.uuid4(),
        title="Early Episode",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now - dt.timedelta(days=10),
        updated_at=now - dt.timedelta(days=10),
    )
    episode_middle = CanonicalEpisode(
        id=uuid.uuid4(),
        series_profile_id=series_id,
        tei_header_id=uuid.uuid4(),
        title="Middle Episode",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now - dt.timedelta(days=5),
        updated_at=now - dt.timedelta(days=5),
    )
    episode_late = CanonicalEpisode(
        id=uuid.uuid4(),
        series_profile_id=series_id,
        tei_header_id=uuid.uuid4(),
        title="Late Episode",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )

    headers = [
        TeiHeader(
            id=ep.tei_header_id,
            title=ep.title,
            payload={"file_desc": {"title": ep.title}},
            raw_xml="<teiHeader/>",
            created_at=ep.created_at,
            updated_at=ep.updated_at,
        )
        for ep in [episode_early, episode_middle, episode_late]
    ]

    return episode_early, episode_middle, episode_late, headers


def _create_reference_document(
    series_id: uuid.UUID, now: dt.datetime
) -> ReferenceDocument:
    """Create and return a reference document for testing."""
    return ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=series_id,
        kind=ReferenceDocumentKind.STYLE_GUIDE,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={},
        created_at=now,
        updated_at=now,
        lock_version=1,
    )


def _create_revisions(
    doc_id: uuid.UUID, now: dt.datetime
) -> tuple[
    ReferenceDocumentRevision, ReferenceDocumentRevision, ReferenceDocumentRevision
]:
    """Create and return three revisions with staggered timestamps."""
    revision_v1 = ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=doc_id,
        content={"version": "1", "rules": ["rule1"]},
        content_hash="hash-v1",
        author="editor",
        change_note="Initial version",
        created_at=now - dt.timedelta(days=15),
    )
    revision_v2 = ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=doc_id,
        content={"version": "2", "rules": ["rule1", "rule2"]},
        content_hash="hash-v2",
        author="editor",
        change_note="Added rule2",
        created_at=now - dt.timedelta(days=8),
    )
    revision_v3 = ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=doc_id,
        content={"version": "3", "rules": ["rule1", "rule2", "rule3"]},
        content_hash="hash-v3",
        author="editor",
        change_note="Added rule3",
        created_at=now - dt.timedelta(days=2),
    )
    return revision_v1, revision_v2, revision_v3


@pytest_asyncio.fixture
async def uow_with_fixtures(session_factory):  # noqa: ANN201, ANN001
    """Provide UOW with series, episodes, reference documents, and revisions."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        now = dt.datetime.now(tz=dt.UTC)

        # Create entities using helper functions
        series = _create_series(now)
        await uow.series_profiles.add(series)
        await uow.flush()  # Ensure series exists before adding episodes

        episode_early, episode_middle, episode_late, headers = (
            _create_episodes_with_headers(series.id, now)
        )
        # Add headers and episodes one-by-one to maintain referential integrity
        for ep, header in zip(
            [episode_early, episode_middle, episode_late], headers, strict=True
        ):
            await uow.tei_headers.add(header)
            await uow.flush()  # Ensure header exists before adding episode
            await uow.episodes.add(ep)

        doc = _create_reference_document(series.id, now)
        await uow.reference_documents.add(doc)

        revision_v1, revision_v2, revision_v3 = _create_revisions(doc.id, now)
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


async def test_resolve_bindings_returns_empty_when_no_bindings_exist(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Resolution returns empty list when no bindings exist for series profile."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]

    resolved = await resolve_bindings(uow, series_profile_id=series.id)

    assert resolved == []


async def test_resolve_bindings_returns_empty_for_nonexistent_episode_id(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Resolution returns empty list when episode_id does not exist in the DB.

    This test exercises the target_episode is None code path in
    _resolve_with_episode_context by creating a binding (so the fast path
    is bypassed) then passing a non-existent episode_id.
    """
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    revision_v1 = fixtures["revision_v1"]
    now = fixtures["now"]

    # Create a binding so resolve_bindings doesn't take the empty fast path
    binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=now,
    )
    await uow.reference_bindings.add(binding)
    await uow.commit()

    nonexistent_episode_id = uuid.uuid4()

    resolved = await resolve_bindings(
        uow,
        series_profile_id=series.id,
        episode_id=nonexistent_episode_id,
    )

    assert resolved == []


async def test_resolve_bindings_returns_default_binding_when_no_episode_context(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """When no episode_id is provided, resolution includes default binding."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    revision_v1 = fixtures["revision_v1"]

    # Create a default binding (effective_from_episode_id = None)
    binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
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


async def _add_default_and_episode_specific_binding(
    uow: CanonicalUnitOfWork,
    fixtures: dict,
    *,
    episode_specific_episode_id: uuid.UUID,
    episode_specific_revision_id: uuid.UUID,
) -> tuple[ReferenceBinding, ReferenceBinding]:
    """Add default binding (v1) and episode-specific binding, then commit."""
    series = fixtures["series"]
    now = fixtures["now"]
    revision_v1 = fixtures["revision_v1"]

    binding_default = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=now - dt.timedelta(days=12),
    )
    binding_episode = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=episode_specific_revision_id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=episode_specific_episode_id,
        created_at=now - dt.timedelta(days=6),
    )
    await uow.reference_bindings.add(binding_default)
    await uow.reference_bindings.add(binding_episode)
    await uow.commit()
    return binding_default, binding_episode


class _ResolutionScenario(typ.NamedTuple):
    episode_specific_episode_key: str
    episode_specific_revision_key: str
    resolve_for_episode_key: str
    expect_default: bool


async def _run_binding_resolution_scenario(
    fixtures: dict,
    scenario: _ResolutionScenario,
) -> None:
    """Drive the add-bindings → resolve → assert lifecycle for a single scenario."""
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]

    binding_default, binding_episode = await _add_default_and_episode_specific_binding(
        uow,
        fixtures,
        episode_specific_episode_id=fixtures[scenario.episode_specific_episode_key].id,
        episode_specific_revision_id=fixtures[
            scenario.episode_specific_revision_key
        ].id,
    )

    resolved = await resolve_bindings(
        uow,
        series_profile_id=series.id,
        episode_id=fixtures[scenario.resolve_for_episode_key].id,
    )

    expected_binding = binding_default if scenario.expect_default else binding_episode
    assert len(resolved) == 1
    assert resolved[0].binding.id == expected_binding.id
    assert resolved[0].revision.id == expected_binding.reference_document_revision_id


async def test_resolve_bindings_selects_episode_specific_binding_over_default(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Episode-specific binding takes precedence over default when provided."""
    await _run_binding_resolution_scenario(
        uow_with_fixtures,
        _ResolutionScenario(
            episode_specific_episode_key="episode_middle",
            episode_specific_revision_key="revision_v2",
            resolve_for_episode_key="episode_middle",
            expect_default=False,
        ),
    )


async def test_resolve_bindings_selects_latest_applicable_episode_binding(  # noqa: PLR0914
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Resolution selects the binding with the latest effective_from_episode_id.

    The selected binding must be on or before the target episode.
    """
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
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=episode_early.id,
        created_at=fixtures["now"] - dt.timedelta(days=11),
    )
    # Binding v2: effective from middle episode
    binding_middle = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v2.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=episode_middle.id,
        created_at=fixtures["now"] - dt.timedelta(days=6),
    )
    # Binding v3: effective from late episode
    binding_late = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v3.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
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


async def test_resolve_bindings_excludes_future_episode_bindings(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
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
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
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
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Fall back to default (effective_from_episode_id=None) when no match."""
    await _run_binding_resolution_scenario(
        uow_with_fixtures,
        _ResolutionScenario(
            episode_specific_episode_key="episode_late",
            episode_specific_revision_key="revision_v3",
            resolve_for_episode_key="episode_early",
            expect_default=True,
        ),
    )


async def _create_episode_template(
    uow: CanonicalUnitOfWork,
    series_id: uuid.UUID,
    now: dt.datetime,
) -> EpisodeTemplate:
    """Create, persist, commit, and return an episode template for testing."""
    template = EpisodeTemplate(
        id=uuid.uuid4(),
        series_profile_id=series_id,
        slug="test-template",
        title="Test Template",
        description=None,
        structure={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )
    await uow.episode_templates.add(template)
    await uow.commit()
    return template


async def test_resolve_bindings_includes_template_bindings(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Template bindings are included when template_id is provided.

    Without episode_id context, both series and template bindings are returned.
    """
    uow: CanonicalUnitOfWork = uow_with_fixtures["uow"]
    series = uow_with_fixtures["series"]
    now = uow_with_fixtures["now"]

    template = await _create_episode_template(uow, series.id, now)

    # Create series-profile binding
    await uow.reference_bindings.add(
        ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=uow_with_fixtures["revision_v1"].id,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            series_profile_id=series.id,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=None,
            created_at=now,
        )
    )

    # Create template binding
    await uow.reference_bindings.add(
        ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=uow_with_fixtures["revision_v2"].id,
            target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
            series_profile_id=None,
            episode_template_id=template.id,
            ingestion_job_id=None,
            effective_from_episode_id=None,
            created_at=now,
        )
    )
    await uow.commit()

    # Resolve with template_id, no episode_id
    resolved = await resolve_bindings(
        uow, series_profile_id=series.id, template_id=template.id
    )

    assert len(resolved) == 2
    resolved_revision_ids = {r.revision.id for r in resolved}
    assert resolved_revision_ids == {
        uow_with_fixtures["revision_v1"].id,
        uow_with_fixtures["revision_v2"].id,
    }


async def test_resolve_bindings_merges_template_with_episode(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Template bindings are always included, series bindings filtered by episode."""
    uow: CanonicalUnitOfWork = uow_with_fixtures["uow"]
    series = uow_with_fixtures["series"]
    now = uow_with_fixtures["now"]

    template = await _create_episode_template(uow, series.id, now)

    # Series binding effective from early episode
    await uow.reference_bindings.add(
        ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=uow_with_fixtures["revision_v1"].id,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            series_profile_id=series.id,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=uow_with_fixtures["episode_early"].id,
            created_at=now,
        )
    )

    # Series binding effective from late episode (should be excluded for early)
    await uow.reference_bindings.add(
        ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=uow_with_fixtures["revision_v3"].id,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            series_profile_id=series.id,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=uow_with_fixtures["episode_late"].id,
            created_at=now,
        )
    )

    # Template binding (always included)
    await uow.reference_bindings.add(
        ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=uow_with_fixtures["revision_v2"].id,
            target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
            series_profile_id=None,
            episode_template_id=template.id,
            ingestion_job_id=None,
            effective_from_episode_id=None,
            created_at=now,
        )
    )
    await uow.commit()

    # Resolve for early episode with template
    resolved = await resolve_bindings(
        uow,
        series_profile_id=series.id,
        template_id=template.id,
        episode_id=uow_with_fixtures["episode_early"].id,
    )

    # Should have: series binding from early + template binding
    # Should NOT have: series binding from late (future episode)
    assert len(resolved) == 2
    resolved_revision_ids = {r.revision.id for r in resolved}
    assert resolved_revision_ids == {
        uow_with_fixtures["revision_v1"].id,
        uow_with_fixtures["revision_v2"].id,
    }


async def test_resolve_bindings_template_only(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Template bindings are returned when only template_id is provided."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    revision_v2 = fixtures["revision_v2"]
    now = fixtures["now"]

    template = await _create_episode_template(uow, series.id, now)

    # Create only template binding, no series bindings
    template_binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v2.id,
        target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
        series_profile_id=None,
        episode_template_id=template.id,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=now,
    )
    await uow.reference_bindings.add(template_binding)
    await uow.commit()

    # Resolve with template_id only
    resolved = await resolve_bindings(
        uow, series_profile_id=series.id, template_id=template.id
    )

    assert len(resolved) == 1
    assert resolved[0].revision.id == revision_v2.id
    assert resolved[0].binding.id == template_binding.id
