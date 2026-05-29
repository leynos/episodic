"""Positive functional tests for get/list reference-binding query operations."""

import typing as typ
import uuid

import pytest
import test_reference_document_service_support as support

from episodic.canonical.domain import (
    ReferenceBindingTargetKind,
)
from episodic.canonical.reference_documents import (
    ReferenceBindingData,
    ReferenceBindingListRequest,
    ReferenceDocumentCreateData,
    ReferenceDocumentRevisionData,
    ReferenceEntityNotFoundError,
    create_reference_binding,
    create_reference_document,
    create_reference_document_revision,
    get_reference_binding,
    list_reference_bindings,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession


service_fixture = support.service_fixture
ServiceFixture = support.ServiceFixture


async def _create_document_and_revision(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a reference document and revision; return (document_id, revision_id)."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        doc = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="style_guide",
                lifecycle_state="active",
                metadata={},
            ),
        )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        rev = await create_reference_document_revision(
            uow,
            document_id=str(doc.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"version": "1"},
                content_hash="hash-query-test",
                author="tester",
                change_note="Query test revision",
            ),
        )
    return doc.id, rev.id


@pytest.mark.asyncio
async def test_get_reference_binding_returns_persisted_binding(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Return a persisted ReferenceBinding with matching id and target fields."""
    _, rev_id = await _create_document_and_revision(session_factory, service_fixture)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        created = await create_reference_binding(
            uow,
            data=ReferenceBindingData(
                reference_document_revision_id=str(rev_id),
                target_kind="series_profile",
                series_profile_id=service_fixture["primary_profile_id"],
                episode_template_id=None,
                ingestion_job_id=None,
                effective_from_episode_id=None,
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        fetched = await get_reference_binding(
            uow,
            binding_id=str(created.id),
        )

    assert fetched.id == created.id
    assert fetched.target_kind == ReferenceBindingTargetKind.SERIES_PROFILE


@pytest.mark.asyncio
async def test_get_reference_binding_raises_not_found_for_unknown_id(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Raise ReferenceEntityNotFoundError for an unknown binding id."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ReferenceEntityNotFoundError, match="not found"):
            await get_reference_binding(
                uow,
                binding_id=str(uuid.uuid4()),
            )


@pytest.mark.asyncio
async def test_list_reference_bindings_returns_all_for_target(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Return all bindings for a given target kind and target id."""
    _doc1_id, rev1_id = await _create_document_and_revision(
        session_factory, service_fixture
    )
    _doc2_id, rev2_id = await _create_document_and_revision(
        session_factory, service_fixture
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await create_reference_binding(
            uow,
            data=ReferenceBindingData(
                reference_document_revision_id=str(rev1_id),
                target_kind="series_profile",
                series_profile_id=service_fixture["primary_profile_id"],
                episode_template_id=None,
                ingestion_job_id=None,
                effective_from_episode_id=None,
            ),
        )
        await create_reference_binding(
            uow,
            data=ReferenceBindingData(
                reference_document_revision_id=str(rev2_id),
                target_kind="series_profile",
                series_profile_id=service_fixture["primary_profile_id"],
                episode_template_id=None,
                ingestion_job_id=None,
                effective_from_episode_id=None,
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        results = await list_reference_bindings(
            uow,
            request=ReferenceBindingListRequest(
                target_kind="series_profile",
                target_id=service_fixture["primary_profile_id"],
                limit=10,
                offset=0,
            ),
        )

    assert len(results) == 2


@pytest.mark.asyncio
async def test_list_reference_bindings_pagination_offset(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Return the second binding when limit=1 and offset=1."""
    _doc1_id, rev1_id = await _create_document_and_revision(
        session_factory, service_fixture
    )
    _doc2_id, rev2_id = await _create_document_and_revision(
        session_factory, service_fixture
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await create_reference_binding(
            uow,
            data=ReferenceBindingData(
                reference_document_revision_id=str(rev1_id),
                target_kind="series_profile",
                series_profile_id=service_fixture["primary_profile_id"],
                episode_template_id=None,
                ingestion_job_id=None,
                effective_from_episode_id=None,
            ),
        )
        second = await create_reference_binding(
            uow,
            data=ReferenceBindingData(
                reference_document_revision_id=str(rev2_id),
                target_kind="series_profile",
                series_profile_id=service_fixture["primary_profile_id"],
                episode_template_id=None,
                ingestion_job_id=None,
                effective_from_episode_id=None,
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        results = await list_reference_bindings(
            uow,
            request=ReferenceBindingListRequest(
                target_kind="series_profile",
                target_id=service_fixture["primary_profile_id"],
                limit=1,
                offset=1,
            ),
        )

    assert len(results) == 1
    assert results[0].id == second.id
