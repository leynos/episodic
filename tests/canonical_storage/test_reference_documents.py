"""Storage tests for reusable reference-document repositories."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid as _uuid

import pytest
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import (
    ReferenceBindingTargetKind,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)
from episodic.canonical.reference_documents.types import ReferenceConflictError
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.fixtures.reference_documents import (
    ReferenceFixtureBundle,
    build_host_bundle,
    build_reference_revision,
    persist_entities_from_fixture,
)

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


async def _assert_host_bundle_round_trip(
    uow: SqlAlchemyUnitOfWork,
    *,
    series_id: uuid.UUID,
    host_bundle: ReferenceFixtureBundle,
) -> None:
    """Assert host reference document/revision/binding round-trip behaviour."""
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
    host_bundle = build_host_bundle(
        series_id=episode_fixture[0].id,
        episode_id=episode_fixture[2].id,
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await persist_entities_from_fixture(uow, episode_fixture)
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
    host_bundle = build_host_bundle(
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
        await persist_entities_from_fixture(uow, episode_fixture)
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
async def test_reference_revision_repository_translates_duplicate_content_hash(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Duplicate ``(document_id, content_hash)`` raises ``ReferenceConflictError``.

    The adapter must translate the uniqueness violation into the domain
    exception so service-layer callers never observe ``IntegrityError``.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    host_bundle = build_host_bundle(
        series_id=episode_fixture[0].id,
        episode_id=episode_fixture[2].id,
    )
    duplicate_revision = build_reference_revision(
        reference_document_id=host_bundle.document.id,
        content={"name": "Different content payload"},
        content_hash=host_bundle.revision.content_hash,
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await persist_entities_from_fixture(uow, episode_fixture)
        await uow.reference_documents.add(host_bundle.document)
        await uow.reference_document_revisions.add(host_bundle.revision)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(
            ReferenceConflictError,
            match=r"duplicate content hash",
        ) as exc_info:
            await uow.reference_document_revisions.add(duplicate_revision)

    assert isinstance(exc_info.value.__cause__, IntegrityError), (
        "expected the original IntegrityError to be chained as the cause"
    )


@pytest.mark.asyncio
async def test_reference_revision_repository_propagates_unrelated_integrity_error(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Foreign-key violations propagate as ``IntegrityError`` unchanged.

    Only the known content-hash uniqueness constraint is translated; other
    integrity failures must remain visible so adapters or callers can surface
    them as configuration or schema errors.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    orphan_revision = ReferenceDocumentRevision(
        id=_uuid.uuid4(),
        reference_document_id=_uuid.uuid4(),
        content={"orphan": True},
        content_hash="hash-orphan",
        author=None,
        change_note=None,
        created_at=dt.datetime.now(dt.UTC),
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await persist_entities_from_fixture(uow, episode_fixture)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(IntegrityError):
            await uow.reference_document_revisions.add(orphan_revision)
