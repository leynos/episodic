"""Reference-document storage test fixtures and builders."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import (
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )
    from episodic.canonical.storage import SqlAlchemyUnitOfWork


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


def build_reference_document(
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


def build_reference_revision(
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


async def persist_base_entities(
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


async def persist_entities_from_fixture(
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
    await persist_base_entities(
        uow,
        BaseEntitiesBundle(
            series=series,
            header=header,
            episode=episode,
            job=job,
        ),
    )


async def add_binding_and_commit(
    uow: SqlAlchemyUnitOfWork,
    binding: ReferenceBinding,
) -> None:
    """Persist one binding and commit the unit of work."""
    await uow.reference_bindings.add(binding)
    await uow.commit()


def build_host_bundle(
    *,
    series_id: uuid.UUID,
    episode_id: uuid.UUID,
) -> ReferenceFixtureBundle:
    """Build a host-profile reference bundle."""
    document = build_reference_document(
        owner_series_profile_id=series_id,
        kind=ReferenceDocumentKind.HOST_PROFILE,
    )
    revision = build_reference_revision(
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


def build_guest_bundle(
    *,
    series_id: uuid.UUID,
    job_id: uuid.UUID,
) -> ReferenceFixtureBundle:
    """Build a guest-profile reference bundle with two target bindings."""
    document = build_reference_document(
        owner_series_profile_id=series_id,
        kind=ReferenceDocumentKind.GUEST_PROFILE,
    )
    revision = build_reference_revision(
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
