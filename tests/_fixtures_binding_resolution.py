"""Binding-resolution domain helpers and pytest fixtures."""

import asyncio
import typing as typ
import uuid

import pytest_asyncio

if typ.TYPE_CHECKING:
    import datetime as dt

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        EpisodeTemplate,
        IngestionJob,
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
        SeriesProfile,
        TeiHeader,
    )
    from episodic.canonical.ports import CanonicalUnitOfWork


def create_series_for_binding_tests(now: dt.datetime) -> SeriesProfile:
    """Create and return a series profile for binding resolution tests."""
    from episodic.canonical.domain import SeriesProfile

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


def create_episodes_with_headers_for_binding_tests(
    series_id: uuid.UUID, now: dt.datetime
) -> tuple[CanonicalEpisode, CanonicalEpisode, CanonicalEpisode, list[TeiHeader]]:
    """Create three episodes with staggered timestamps and their TEI headers."""
    import datetime as dt

    from episodic.canonical.domain import (
        ApprovalState,
        CanonicalEpisode,
        EpisodeStatus,
        TeiHeader,
    )

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


def create_reference_document_for_binding_tests(
    series_id: uuid.UUID, now: dt.datetime
) -> ReferenceDocument:
    """Create and return a reference document for binding resolution tests."""
    from episodic.canonical.domain import (
        ReferenceDocument,
        ReferenceDocumentKind,
        ReferenceDocumentLifecycleState,
    )

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


def create_revisions_for_binding_tests(
    doc_id: uuid.UUID, now: dt.datetime
) -> tuple[
    ReferenceDocumentRevision, ReferenceDocumentRevision, ReferenceDocumentRevision
]:
    """Create and return three revisions with staggered timestamps."""
    import datetime as dt

    from episodic.canonical.domain import ReferenceDocumentRevision

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


async def create_episode_template_for_binding_tests(
    uow: CanonicalUnitOfWork, series_id: uuid.UUID, now: dt.datetime
) -> EpisodeTemplate:
    """Create, persist, commit, and return an episode template for testing."""
    from episodic.canonical.domain import EpisodeTemplate

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


class BindingFixtures(typ.TypedDict):
    """Type definition for uow_with_binding_fixtures fixture."""

    uow: CanonicalUnitOfWork
    series: SeriesProfile
    episode_early: CanonicalEpisode
    episode_middle: CanonicalEpisode
    episode_late: CanonicalEpisode
    doc: ReferenceDocument
    revision_v1: ReferenceDocumentRevision
    revision_v2: ReferenceDocumentRevision
    revision_v3: ReferenceDocumentRevision
    now: dt.datetime


@pytest_asyncio.fixture
async def uow_with_fixtures(
    uow_with_binding_fixtures: BindingFixtures,
) -> BindingFixtures:
    """Backward-compatible alias for binding-resolution tests."""
    await asyncio.sleep(0)
    return uow_with_binding_fixtures


@pytest_asyncio.fixture
async def binding_test_uow(
    uow_with_binding_fixtures: BindingFixtures,
) -> CanonicalUnitOfWork:
    """Return the shared unit of work for binding-resolution tests."""
    await asyncio.sleep(0)
    return uow_with_binding_fixtures["uow"]


@pytest_asyncio.fixture
async def binding_test_series(
    uow_with_binding_fixtures: BindingFixtures,
) -> SeriesProfile:
    """Return the shared series profile for binding-resolution tests."""
    await asyncio.sleep(0)
    return uow_with_binding_fixtures["series"]


@pytest_asyncio.fixture
async def binding_test_episode(
    uow_with_binding_fixtures: BindingFixtures,
) -> CanonicalEpisode:
    """Return the default episode fixture for snapshot tests."""
    await asyncio.sleep(0)
    return uow_with_binding_fixtures["episode_early"]


@pytest_asyncio.fixture
async def binding_test_document(
    uow_with_binding_fixtures: BindingFixtures,
) -> ReferenceDocument:
    """Return the shared reference document for binding-resolution tests."""
    await asyncio.sleep(0)
    return uow_with_binding_fixtures["doc"]


@pytest_asyncio.fixture
async def binding_test_revision_v1(
    uow_with_binding_fixtures: BindingFixtures,
) -> ReferenceDocumentRevision:
    """Return the first reference-document revision for binding tests."""
    await asyncio.sleep(0)
    return uow_with_binding_fixtures["revision_v1"]


@pytest_asyncio.fixture
async def binding_test_now(
    uow_with_binding_fixtures: BindingFixtures,
) -> dt.datetime:
    """Return the common timestamp baseline for binding-resolution tests."""
    await asyncio.sleep(0)
    return uow_with_binding_fixtures["now"]


@pytest_asyncio.fixture
async def binding_snapshot_job(
    binding_test_uow: CanonicalUnitOfWork,
    binding_test_series: SeriesProfile,
    binding_test_episode: CanonicalEpisode,
    binding_test_now: dt.datetime,
) -> IngestionJob:
    """Persist an ingestion job for reference snapshot tests."""
    from episodic.canonical.domain import IngestionJob, IngestionStatus

    job = IngestionJob(
        id=uuid.uuid4(),
        series_profile_id=binding_test_series.id,
        target_episode_id=binding_test_episode.id,
        status=IngestionStatus.COMPLETED,
        requested_at=binding_test_now,
        started_at=binding_test_now,
        completed_at=binding_test_now,
        error_message=None,
        created_at=binding_test_now,
        updated_at=binding_test_now,
    )
    await binding_test_uow.ingestion_jobs.add(job)
    await binding_test_uow.commit()
    return job


@pytest_asyncio.fixture
async def binding_snapshot_reference_binding(
    binding_test_uow: CanonicalUnitOfWork,
    binding_test_series: SeriesProfile,
    binding_test_revision_v1: ReferenceDocumentRevision,
    binding_test_now: dt.datetime,
) -> ReferenceBinding:
    """Persist one series-level reference binding for snapshot tests."""
    from episodic.canonical.domain import (
        ReferenceBinding,
        ReferenceBindingTargetKind,
    )

    binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=binding_test_revision_v1.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=binding_test_series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=binding_test_now,
    )
    await binding_test_uow.reference_bindings.add(binding)
    await binding_test_uow.commit()
    return binding


@pytest_asyncio.fixture
async def uow_with_binding_fixtures(
    session_factory: async_sessionmaker[AsyncSession],
) -> typ.AsyncIterator[BindingFixtures]:
    """Provide UOW with series, episodes, reference documents, and revisions."""
    import datetime as dt

    from episodic.canonical.storage.uow import SqlAlchemyUnitOfWork

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        now = dt.datetime.now(tz=dt.UTC)

        series = create_series_for_binding_tests(now)
        await uow.series_profiles.add(series)
        await uow.flush()

        episode_early, episode_middle, episode_late, headers = (
            create_episodes_with_headers_for_binding_tests(series.id, now)
        )
        for ep, header in zip(
            [episode_early, episode_middle, episode_late], headers, strict=True
        ):
            await uow.tei_headers.add(header)
            await uow.flush()
            await uow.episodes.add(ep)

        doc = create_reference_document_for_binding_tests(series.id, now)
        await uow.reference_documents.add(doc)

        revision_v1, revision_v2, revision_v3 = create_revisions_for_binding_tests(
            doc.id, now
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
