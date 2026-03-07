"""Series-alignment service tests for reusable reference documents."""

import typing as typ

import pytest
import test_reference_document_service_support as support

from episodic.canonical.reference_documents import (
    ReferenceEntityNotFoundError,
    get_reference_document,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


service_fixture = support.service_fixture
ServiceFixture = support.ServiceFixture


@pytest.mark.asyncio
async def test_series_aligned_host_guest_access_and_binding_workflow(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Host/guest docs should be series aligned and bindable to templates."""
    host_document, guest_document = await support._create_host_and_guest_documents(
        session_factory,
        service_fixture,
    )
    host_revision = await support._create_revisions_for_host_and_guest(
        session_factory,
        service_fixture,
        host_document,
        guest_document,
    )
    host_documents, guest_documents = await support._list_documents_and_bind(
        session_factory,
        service_fixture,
        host_revision,
    )

    assert len(host_documents) == 1, "Expected one host document for the series."
    assert len(guest_documents) == 1, "Expected one guest document for the series."

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ReferenceEntityNotFoundError):
            await get_reference_document(
                uow,
                document_id=str(host_document.id),
                owner_series_profile_id=service_fixture["secondary_profile_id"],
            )
