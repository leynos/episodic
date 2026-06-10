"""Functional regression tests for the reference-document bindings facade."""

import typing as typ
import uuid

import pytest
import test_reference_document_service_support as support

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
)
from episodic.canonical.reference_documents import (
    ReferenceBindingData,
    ReferenceBindingListRequest,
    ReferenceDocumentCreateData,
    ReferenceDocumentRevisionData,
    bindings,
    create_reference_document,
    create_reference_document_revision,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession


service_fixture = support.service_fixture
ServiceFixture = support.ServiceFixture


async def _create_revision(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
    *,
    content_hash: str,
) -> uuid.UUID:
    """Create a reference-document revision for facade binding tests."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        document = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="style_guide",
                lifecycle_state="active",
                metadata={"title": content_hash},
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        revision = await create_reference_document_revision(
            uow,
            document_id=str(document.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"version": content_hash},
                content_hash=content_hash,
                author="tester@example.com",
                change_note="Facade regression test revision",
            ),
        )

    return revision.id


async def _create_series_binding(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
    *,
    content_hash: str = "facade-binding",
) -> ReferenceBinding:
    """Create a series-profile binding through the bindings facade."""
    revision_id = await _create_revision(
        session_factory,
        service_fixture,
        content_hash=content_hash,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        return await bindings.create_reference_binding(
            uow,
            data=ReferenceBindingData(
                reference_document_revision_id=str(revision_id),
                target_kind="series_profile",
                series_profile_id=service_fixture["primary_profile_id"],
                episode_template_id=None,
                ingestion_job_id=None,
                effective_from_episode_id=None,
            ),
        )


def test_bindings_facade_exports_public_entry_points() -> None:
    """Expose the expected public binding entry points."""
    assert set(bindings.__all__) == {
        "create_reference_binding",
        "get_reference_binding",
        "list_reference_bindings",
        "list_reference_bindings_paged",
    }


@pytest.mark.asyncio
async def test_create_reference_binding_returns_created_binding(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Create and return a series-profile binding through the facade."""
    binding = await _create_series_binding(session_factory, service_fixture)

    assert isinstance(binding, ReferenceBinding)
    assert binding.target_kind == ReferenceBindingTargetKind.SERIES_PROFILE
    assert binding.series_profile_id == uuid.UUID(service_fixture["primary_profile_id"])


@pytest.mark.asyncio
async def test_get_reference_binding_returns_matching_binding(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Fetch a persisted binding through the facade."""
    created = await _create_series_binding(session_factory, service_fixture)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        fetched = await bindings.get_reference_binding(
            uow,
            binding_id=str(created.id),
        )

    assert isinstance(fetched, ReferenceBinding)
    assert fetched.id == created.id
    assert (
        fetched.reference_document_revision_id == created.reference_document_revision_id
    )


@pytest.mark.asyncio
async def test_list_reference_bindings_returns_target_page(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """List target bindings through the facade."""
    created = await _create_series_binding(session_factory, service_fixture)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        results = await bindings.list_reference_bindings(
            uow,
            request=ReferenceBindingListRequest(
                target_kind="series_profile",
                target_id=service_fixture["primary_profile_id"],
                limit=10,
                offset=0,
            ),
        )

    assert isinstance(results, list)
    assert [binding.id for binding in results] == [created.id]
    assert results[0].series_profile_id == created.series_profile_id


@pytest.mark.asyncio
async def test_list_reference_bindings_paged_returns_page_and_total(
    session_factory: cabc.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """List target bindings and total count through the facade."""
    first = await _create_series_binding(
        session_factory,
        service_fixture,
        content_hash="facade-binding-paged-first",
    )
    second = await _create_series_binding(
        session_factory,
        service_fixture,
        content_hash="facade-binding-paged-second",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        results, total = await bindings.list_reference_bindings_paged(
            uow,
            request=ReferenceBindingListRequest(
                target_kind="series_profile",
                target_id=service_fixture["primary_profile_id"],
                limit=1,
                offset=1,
            ),
        )

    assert isinstance(results, list)
    assert total == 2
    assert [binding.id for binding in results] == [second.id]
    assert first.id != second.id
