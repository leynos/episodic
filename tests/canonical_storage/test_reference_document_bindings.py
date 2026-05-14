"""Storage tests for reusable reference-document bindings."""

import dataclasses as dc
import typing as typ
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import ReferenceBindingTargetKind
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.fixtures.reference_documents import (
    add_binding_and_commit,
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
            IntegrityError,
            match=r"uq_ref_doc_bindings_series_rev_no_effective",
        ):
            await add_binding_and_commit(uow, duplicate_binding)


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
