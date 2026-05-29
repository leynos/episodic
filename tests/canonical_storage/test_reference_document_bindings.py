"""Storage tests for reusable reference-document bindings."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import ReferenceBinding, ReferenceBindingTargetKind
from episodic.canonical.reference_documents.types import ReferenceConflictError
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.fixtures.reference_documents import (
    build_guest_bundle,
    persist_entities_from_fixture,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


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
    guest_bundle = build_guest_bundle(
        series_id=episode_fixture[0].id,
        job_id=episode_fixture[3].id,
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await persist_entities_from_fixture(uow, episode_fixture)
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


@pytest.mark.asyncio
async def test_reference_binding_repository_lists_multiple_targets(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Binding repository should batch lookups for several target identifiers."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    guest_bundle = build_guest_bundle(
        series_id=episode_fixture[0].id,
        job_id=episode_fixture[3].id,
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await persist_entities_from_fixture(uow, episode_fixture)
        await uow.reference_documents.add(guest_bundle.document)
        await uow.reference_document_revisions.add(guest_bundle.revision)
        await uow.flush()
        for binding in guest_bundle.bindings:
            await uow.reference_bindings.add(binding)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        series_bindings = await uow.reference_bindings.list_for_targets(
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            target_ids={episode_fixture[0].id, uuid.uuid4()},
        )

    assert [binding.id for binding in series_bindings] == [
        guest_bundle.bindings[0].id
    ], "expected only matching series-target bindings from batched lookup"


@pytest.mark.asyncio
async def test_reference_binding_repository_translates_duplicate_target_revision(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Duplicate series-target bindings raise ``ReferenceConflictError``.

    The storage adapter translates the underlying uniqueness violation into
    the domain conflict exception so callers never see ``IntegrityError``.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    guest_bundle = build_guest_bundle(
        series_id=episode_fixture[0].id,
        job_id=episode_fixture[3].id,
    )
    duplicate_binding = dc.replace(guest_bundle.bindings[0], id=uuid.uuid4())

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await persist_entities_from_fixture(uow, episode_fixture)
        await uow.reference_documents.add(guest_bundle.document)
        await uow.reference_document_revisions.add(guest_bundle.revision)
        await uow.flush()
        await uow.reference_bindings.add(guest_bundle.bindings[0])
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(
            ReferenceConflictError,
            match=r"duplicate target/revision binding",
        ):
            await uow.reference_bindings.add(duplicate_binding)


@pytest.mark.asyncio
async def test_reference_binding_repository_propagates_unrelated_integrity_error(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Unrelated integrity violations (e.g. FK) still surface as ``IntegrityError``.

    The translation is scoped to known uniqueness constraint names; everything
    else must propagate unchanged so callers can diagnose unexpected failures.
    """
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    series = episode_fixture[0]
    orphan_binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=uuid.uuid4(),
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=dt.datetime.now(dt.UTC),
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await persist_entities_from_fixture(uow, episode_fixture)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        with pytest.raises(IntegrityError):
            await uow.reference_bindings.add(orphan_binding)
