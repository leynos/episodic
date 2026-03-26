"""Validation tests for reference binding resolution algorithm."""

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
    SeriesProfile,
    TeiHeader,
)
from episodic.canonical.reference_documents.resolution import resolve_bindings
from tests.conftest import uow_with_binding_fixtures  # noqa: F401

pytestmark = pytest.mark.asyncio


# Alias fixture for consistency
@pytest_asyncio.fixture
def uow_with_fixtures(uow_with_binding_fixtures):  # noqa: ANN001, ANN201, F811
    """Alias for uow_with_binding_fixtures from conftest."""
    yield uow_with_binding_fixtures


async def test_resolve_bindings_returns_empty_for_episode_from_wrong_series(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Resolution returns empty list when episode belongs to a different series."""
    fixtures = uow_with_fixtures
    uow = fixtures["uow"]
    series = fixtures["series"]
    now = fixtures["now"]

    other_series = SeriesProfile(
        id=uuid.uuid4(),
        title="Other Series",
        slug="other-series",
        description="Another series",
        configuration={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )
    await uow.series_profiles.add(other_series)
    await uow.flush()

    other_header = TeiHeader(
        id=uuid.uuid4(),
        title="Other Episode",
        payload={"file_desc": {"title": "Other Episode"}},
        raw_xml="<teiHeader/>",
        created_at=now,
        updated_at=now,
    )
    await uow.tei_headers.add(other_header)
    await uow.flush()

    other_episode = CanonicalEpisode(
        id=uuid.uuid4(),
        series_profile_id=other_series.id,
        tei_header_id=other_header.id,
        title="Other Episode",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    await uow.episodes.add(other_episode)
    await uow.commit()

    resolved = await resolve_bindings(
        uow,
        series_profile_id=series.id,
        episode_id=other_episode.id,
    )

    assert resolved == []


async def test_resolve_bindings_skips_template_from_wrong_series(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Resolution skips template bindings when template belongs to different series."""
    fixtures = uow_with_fixtures
    uow = fixtures["uow"]
    series = fixtures["series"]
    revision_v1 = fixtures["revision_v1"]
    now = fixtures["now"]

    other_series = SeriesProfile(
        id=uuid.uuid4(),
        title="Other Series",
        slug="other-series",
        description="Another series",
        configuration={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )
    await uow.series_profiles.add(other_series)
    await uow.flush()

    other_template = EpisodeTemplate(
        id=uuid.uuid4(),
        series_profile_id=other_series.id,
        slug="other-template",
        title="Other Template",
        description=None,
        structure={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )
    await uow.episode_templates.add(other_template)
    await uow.commit()

    await uow.reference_bindings.add(
        ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=revision_v1.id,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            series_profile_id=series.id,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=None,
            created_at=now,
        )
    )
    await uow.commit()

    resolved = await resolve_bindings(
        uow,
        series_profile_id=series.id,
        template_id=other_template.id,
    )

    assert len(resolved) == 1
    assert resolved[0].revision.id == revision_v1.id
