"""Storage tests for reusable reference-document repositories."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


@dc.dataclass(frozen=True, slots=True)
class ReferenceFixtureBundle:
    """Bundle reusable reference document entities for storage tests."""

    document: ReferenceDocument
    revision: ReferenceDocumentRevision
    bindings: tuple[ReferenceBinding, ...]


@dc.dataclass(frozen=True, slots=True)
class BaseEntitiesBundle:
    """Bundle base canonical entities needed for reference-binding tests."""

    series: SeriesProfile
    header: TeiHeader
    episode: CanonicalEpisode
    job: IngestionJob


def _build_reference_document(
    *,
    owner_series_profile_id: uuid.UUID,
    kind: ReferenceDocumentKind,
) -> ReferenceDocument:
    """Build a reusable reference document for tests."""
    now = dt.datetime.now(dt.UTC)
    return ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=owner_series_profile_id,
        kind=kind,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={"title": f"{kind.value}-doc"},
        created_at=now,
        updated_at=now,
    )


def _build_reference_revision(
    *,
    reference_document_id: uuid.UUID,
    content: dict[str, object],
    content_hash: str,
) -> ReferenceDocumentRevision:
    """Build a reusable reference document revision for tests."""
    return ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=reference_document_id,
        content=content,
        content_hash=content_hash,
        author="author@example.com",
        change_note="Initial revision",
        created_at=dt.datetime.now(dt.UTC),
    )


async def _persist_base_entities(
    uow: SqlAlchemyUnitOfWork,
    entities: BaseEntitiesBundle,
) -> None:
    """Persist prerequisite canonical entities for binding FKs."""
    await uow.series_profiles.add(entities.series)
    await uow.tei_headers.add(entities.header)
    await uow.commit()
    await uow.episodes.add(entities.episode)
    await uow.ingestion_jobs.add(entities.job)
    await uow.commit()


async def _persist_entities_from_fixture(
    uow: SqlAlchemyUnitOfWork,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Persist prerequisite entities from the shared episode fixture."""
    series, header, episode, job, _ = episode_fixture
    await _persist_base_entities(
        uow,
        BaseEntitiesBundle(
            series=series,
            header=header,
            episode=episode,
            job=job,
        ),
    )


async def _add_binding_and_commit(
    uow: SqlAlchemyUnitOfWork,
    binding: ReferenceBinding,
) -> None:
    """Persist one binding and commit the unit of work."""
    await uow.reference_bindings.add(binding)
    await uow.commit()


async def _assert_host_bundle_round_trip(
    uow: SqlAlchemyUnitOfWork,
    *,
    series_id: uuid.UUID,
    host_bundle: ReferenceFixtureBundle,
) -> None:
    """Assert host reference document/revision/binding round-trip behavior."""
    fetched_document = await uow.reference_documents.get(host_bundle.document.id)
    assert fetched_document is not None, "Expected stored reference document."
    assert fetched_document.kind is ReferenceDocumentKind.HOST_PROFILE, (
        "expected HOST_PROFILE kind for stored host reference document"
    )

    series_documents = await uow.reference_documents.list_for_series(series_id)
    assert len(series_documents) == 1, "expected one series document for host bundle"
    assert series_documents[0].id == host_bundle.document.id, (
        "expected series document id to match host bundle document id"
    )

    revisions = await uow.reference_document_revisions.list_for_document(
        host_bundle.document.id
    )
    assert len(revisions) == 1, "expected one revision for host bundle document"
    assert revisions[0].id == host_bundle.revision.id, (
        "expected revision id to match host bundle revision id"
    )

    latest = await uow.reference_document_revisions.get_latest_for_document(
        host_bundle.document.id
    )
    assert latest is not None, "expected latest revision to exist for host bundle"
    assert latest.id == host_bundle.revision.id, (
        "expected latest revision id to match host bundle revision id"
    )

    series_bindings = await uow.reference_bindings.list_for_target(
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        target_id=series_id,
    )
    assert len(series_bindings) == 1, "expected one series binding for host bundle"
    assert series_bindings[0].id == host_bundle.bindings[0].id, (
        "expected series binding id to match host bundle binding id"
    )


def _build_host_bundle(
    *,
    series_id: uuid.UUID,
    episode_id: uuid.UUID,
) -> ReferenceFixtureBundle:
    """Build a host-profile reference bundle."""
    document = _build_reference_document(
        owner_series_profile_id=series_id,
        kind=ReferenceDocumentKind.HOST_PROFILE,
    )
    revision = _build_reference_revision(
        reference_document_id=document.id,
        content={"name": "Host One"},
        content_hash="hash-host-1",
    )
    binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series_id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=episode_id,
        created_at=dt.datetime.now(dt.UTC),
    )
    return ReferenceFixtureBundle(
        document=document,
        revision=revision,
        bindings=(binding,),
    )


def _build_guest_bundle(
    *,
    series_id: uuid.UUID,
    job_id: uuid.UUID,
) -> ReferenceFixtureBundle:
    """Build a guest-profile reference bundle with two target bindings."""
    document = _build_reference_document(
        owner_series_profile_id=series_id,
        kind=ReferenceDocumentKind.GUEST_PROFILE,
    )
    revision = _build_reference_revision(
        reference_document_id=document.id,
        content={"name": "Guest One"},
        content_hash="hash-guest-1",
    )
    series_binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series_id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=dt.datetime.now(dt.UTC),
    )
    job_binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision.id,
        target_kind=ReferenceBindingTargetKind.INGESTION_JOB,
        series_profile_id=None,
        episode_template_id=None,
        ingestion_job_id=job_id,
        effective_from_episode_id=None,
        created_at=dt.datetime.now(dt.UTC),
    )
    return ReferenceFixtureBundle(
        document=document,
        revision=revision,
        bindings=(series_binding, job_binding),
    )


@pytest.mark.asyncio
async def test_reference_document_repositories_round_trip(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Reference document repositories should persist and retrieve records."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    host_bundle = _build_host_bundle(
        series_id=episode_fixture[0].id,
        episode_id=episode_fixture[2].id,
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await _persist_entities_from_fixture(uow, episode_fixture)
        await uow.reference_documents.add(host_bundle.document)
        await uow.reference_document_revisions.add(host_bundle.revision)
        await uow.flush()
        await uow.reference_bindings.add(host_bundle.bindings[0])
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await _assert_host_bundle_round_trip(
            uow,
            series_id=episode_fixture[0].id,
            host_bundle=host_bundle,
        )


@pytest.mark.asyncio
async def test_reference_document_repository_update_persists_changes(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Reference document updates should persist lifecycle and metadata changes."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    host_bundle = _build_host_bundle(
        series_id=episode_fixture[0].id,
        episode_id=episode_fixture[2].id,
    )
    updated_document = dc.replace(
        host_bundle.document,
        lifecycle_state=ReferenceDocumentLifecycleState.ARCHIVED,
        metadata={"title": "host_profile-doc", "status": "archived"},
        updated_at=dt.datetime.now(dt.UTC),
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await _persist_entities_from_fixture(uow, episode_fixture)
        await uow.reference_documents.add(host_bundle.document)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.reference_documents.update(updated_document)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        refreshed = await uow.reference_documents.get(updated_document.id)
        assert refreshed is not None, "expected updated document to be retrievable"
        assert refreshed.lifecycle_state is ReferenceDocumentLifecycleState.ARCHIVED, (
            "expected lifecycle_state to be ARCHIVED after update"
        )
        assert refreshed.metadata == {
            "title": "host_profile-doc",
            "status": "archived",
        }, "expected archived metadata payload to persist after update"


@pytest.mark.asyncio
async def test_reference_binding_repository_enforces_unique_target_revision(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Duplicate series-target bindings for one revision should fail."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    guest_bundle = _build_guest_bundle(
        series_id=episode_fixture[0].id,
        job_id=episode_fixture[3].id,
    )
    duplicate_binding = dc.replace(guest_bundle.bindings[0], id=uuid.uuid4())

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await _persist_entities_from_fixture(uow, episode_fixture)
        await uow.reference_documents.add(guest_bundle.document)
        await uow.reference_document_revisions.add(guest_bundle.revision)
        await uow.flush()
        await uow.reference_bindings.add(guest_bundle.bindings[0])
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(
            IntegrityError,
            match=r"uq_ref_doc_bindings_series_rev_no_effective",
        ):
            await _add_binding_and_commit(uow, duplicate_binding)


@pytest.mark.asyncio
async def test_reference_binding_repository_filters_by_target_kind(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Binding repository should return only bindings for requested targets."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    guest_bundle = _build_guest_bundle(
        series_id=episode_fixture[0].id,
        job_id=episode_fixture[3].id,
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await _persist_entities_from_fixture(uow, episode_fixture)
        await uow.reference_documents.add(guest_bundle.document)
        await uow.reference_document_revisions.add(guest_bundle.revision)
        await uow.flush()
        for binding in guest_bundle.bindings:
            await uow.reference_bindings.add(binding)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        series_bindings = await uow.reference_bindings.list_for_target(
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            target_id=episode_fixture[0].id,
        )
        assert [binding.id for binding in series_bindings] == [
            guest_bundle.bindings[0].id
        ], "expected only the series-target binding for series lookup"

        job_bindings = await uow.reference_bindings.list_for_target(
            target_kind=ReferenceBindingTargetKind.INGESTION_JOB,
            target_id=episode_fixture[3].id,
        )
        assert [binding.id for binding in job_bindings] == [
            guest_bundle.bindings[1].id
        ], "expected only the ingestion-job-target binding for job lookup"
