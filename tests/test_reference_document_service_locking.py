"""Optimistic-lock service tests for reusable reference documents."""

import typing as typ

import pytest
import test_reference_document_service_support as support

from episodic.canonical.reference_documents import (
    ReferenceDocumentCreateData,
    ReferenceDocumentUpdateRequest,
    ReferenceRevisionConflictError,
    create_reference_document,
    update_reference_document,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


service_fixture = support.service_fixture
ServiceFixture = support.ServiceFixture


@pytest.mark.asyncio
async def test_update_reference_document_rejects_stale_lock_version(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Updating with a stale expected lock version should raise conflict."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        created = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="host_profile",
                lifecycle_state="active",
                metadata={"name": "Host Service One"},
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        updated = await update_reference_document(
            uow,
            request=ReferenceDocumentUpdateRequest(
                document_id=str(created.id),
                owner_series_profile_id=service_fixture["primary_profile_id"],
                expected_lock_version=1,
                lifecycle_state="active",
                metadata={"name": "Host Service One", "status": "updated"},
            ),
        )

    assert updated.lock_version == 2, "Expected lock version increment on update."

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ReferenceRevisionConflictError):
            await update_reference_document(
                uow,
                request=ReferenceDocumentUpdateRequest(
                    document_id=str(created.id),
                    owner_series_profile_id=service_fixture["primary_profile_id"],
                    expected_lock_version=1,
                    lifecycle_state="archived",
                    metadata={"name": "Host Service One", "status": "stale"},
                ),
            )
