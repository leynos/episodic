"""Revision-history service tests for reusable reference documents."""

import typing as typ

import pytest

from episodic.canonical.reference_documents import (
    ReferenceDocumentCreateData,
    ReferenceDocumentRevisionData,
    ReferenceDocumentRevisionListRequest,
    create_reference_document,
    create_reference_document_revision,
    get_reference_document_revision,
    list_reference_document_revisions,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
import test_reference_document_service_support as support

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


service_fixture = support.service_fixture
ServiceFixture = support.ServiceFixture


@pytest.mark.asyncio
async def test_reference_document_revision_history_round_trip(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Revision create/list/get should provide immutable change-history access."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        created = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="research_brief",
                lifecycle_state="active",
                metadata={"topic": "Episode context"},
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        first = await create_reference_document_revision(
            uow,
            document_id=str(created.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"summary": "first revision"},
                content_hash="service-hash-1",
                author="service@example.com",
                change_note="First revision",
            ),
        )
        second = await create_reference_document_revision(
            uow,
            document_id=str(created.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"summary": "second revision"},
                content_hash="service-hash-2",
                author="service@example.com",
                change_note="Second revision",
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        history = await list_reference_document_revisions(
            uow,
            request=ReferenceDocumentRevisionListRequest(
                document_id=str(created.id),
                owner_series_profile_id=service_fixture["primary_profile_id"],
                limit=10,
                offset=0,
            ),
        )
        fetched_second = await get_reference_document_revision(
            uow,
            revision_id=str(second.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
        )

    assert [item.id for item in history] == [first.id, second.id], (
        "Expected revision history to preserve creation order."
    )
    assert fetched_second.id == second.id, "Expected to fetch revision by id."
