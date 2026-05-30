"""Integration tests for brief reference-document resolution strategies."""

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    ReferenceBinding,
    ReferenceBindingTargetKind,
    SeriesProfile,
    TeiHeader,
)
from episodic.canonical.profile_templates._brief_reference_documents import (
    _load_legacy_reference_documents,
    _validate_episode_for_brief,
)
from episodic.canonical.profile_templates.types import EntityNotFoundError
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.fixtures.binding import BindingFixtures


@pytest.mark.asyncio
async def test_validate_episode_for_brief_rejects_mismatched_series(
    session_factory: cabc.Callable[[], AsyncSession],
) -> None:
    """Raise EntityNotFoundError when episode exists but owns a different profile."""
    now = dt.datetime.now(tz=dt.UTC)
    series_id = uuid.uuid4()
    other_profile_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    header_id = uuid.uuid4()

    series = SeriesProfile(
        id=series_id,
        slug="test-series",
        title="Test Series",
        description=None,
        configuration={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )
    header = TeiHeader(
        id=header_id,
        title="Test Header",
        payload={},
        raw_xml="<teiHeader/>",
        created_at=now,
        updated_at=now,
    )
    episode = CanonicalEpisode(
        id=episode_id,
        series_profile_id=series_id,
        tei_header_id=header_id,
        title="Test Episode",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.series_profiles.add(series)
        await uow.flush()
        await uow.tei_headers.add(header)
        await uow.flush()
        await uow.episodes.add(episode)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(EntityNotFoundError, match="not found"):
            await _validate_episode_for_brief(
                uow,
                episode_id=episode_id,
                profile_id=other_profile_id,
            )


@pytest.mark.asyncio
async def test_load_legacy_reference_documents_returns_series_binding(
    uow_with_binding_fixtures: BindingFixtures,
) -> None:
    """Return serialised bindings for a SERIES_PROFILE target."""
    fixtures = uow_with_binding_fixtures
    uow = fixtures["uow"]
    series = fixtures["series"]
    revision_v1 = fixtures["revision_v1"]

    series_binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=dt.datetime.now(tz=dt.UTC),
    )
    await uow.reference_bindings.add(series_binding)
    await uow.commit()

    results = await _load_legacy_reference_documents(
        uow,
        profile_id=series.id,
        template_items=[],
    )

    assert len(results) == 1
    assert results[0]["target_kind"] == "series_profile"


@pytest.mark.asyncio
async def test_load_legacy_reference_documents_returns_empty_when_no_bindings(
    uow_with_binding_fixtures: BindingFixtures,
) -> None:
    """Return an empty list when no bindings exist for the targets."""
    fixtures = uow_with_binding_fixtures

    results = await _load_legacy_reference_documents(
        fixtures["uow"],
        profile_id=fixtures["series"].id,
        template_items=[],
    )

    assert results == []
