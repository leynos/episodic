"""Validation and pagination service tests for reusable reference documents."""

import typing as typ

import pytest

from episodic.canonical.reference_documents import (
    ReferenceBindingListRequest,
    ReferenceDocumentCreateData,
    ReferenceDocumentListRequest,
    ReferenceValidationError,
    create_reference_document,
    get_reference_document,
    list_reference_bindings,
    list_reference_documents,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
import test_reference_document_service_support as support

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


service_fixture = support.service_fixture
ServiceFixture = support.ServiceFixture


@pytest.mark.asyncio
async def test_public_services_reject_invalid_uuid_and_enum_values(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Public service functions should reject invalid UUID and enum values."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(
            ReferenceValidationError,
            match="Invalid UUID for document_id",
        ):
            await get_reference_document(
                uow,
                document_id="not-a-uuid",
                owner_series_profile_id=service_fixture["primary_profile_id"],
            )

        with pytest.raises(
            ReferenceValidationError,
            match="Unsupported reference document kind",
        ):
            await create_reference_document(
                uow,
                data=ReferenceDocumentCreateData(
                    owner_series_profile_id=service_fixture["primary_profile_id"],
                    kind="not-a-valid-kind",
                    lifecycle_state="active",
                    metadata={"name": "invalid kind"},
                ),
            )

        with pytest.raises(
            ReferenceValidationError,
            match="Unsupported reference document lifecycle_state",
        ):
            await create_reference_document(
                uow,
                data=ReferenceDocumentCreateData(
                    owner_series_profile_id=service_fixture["primary_profile_id"],
                    kind="host_profile",
                    lifecycle_state="not-a-valid-state",
                    metadata={"name": "invalid state"},
                ),
            )

        with pytest.raises(
            ReferenceValidationError,
            match="Unsupported reference binding target_kind",
        ):
            await list_reference_bindings(
                uow,
                request=ReferenceBindingListRequest(
                    target_kind="not-a-valid-target-kind",
                    target_id=service_fixture["primary_profile_id"],
                    limit=10,
                    offset=0,
                ),
            )


@pytest.mark.asyncio
async def test_list_reference_documents_rejects_invalid_pagination(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Document listing should reject invalid pagination values."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await support._assert_list_rejects_invalid_pagination(
            uow,
            lambda: list_reference_documents(
                uow,
                request=ReferenceDocumentListRequest(
                    owner_series_profile_id=service_fixture["primary_profile_id"],
                    kind=None,
                    limit=0,
                    offset=0,
                ),
            ),
            lambda: list_reference_documents(
                uow,
                request=ReferenceDocumentListRequest(
                    owner_series_profile_id=service_fixture["primary_profile_id"],
                    kind=None,
                    limit=10,
                    offset=-1,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_list_reference_bindings_rejects_invalid_pagination(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Binding listing should reject invalid pagination values."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await support._assert_list_rejects_invalid_pagination(
            uow,
            lambda: list_reference_bindings(
                uow,
                request=ReferenceBindingListRequest(
                    target_kind="series_profile",
                    target_id=service_fixture["primary_profile_id"],
                    limit=0,
                    offset=0,
                ),
            ),
            lambda: list_reference_bindings(
                uow,
                request=ReferenceBindingListRequest(
                    target_kind="series_profile",
                    target_id=service_fixture["primary_profile_id"],
                    limit=10,
                    offset=-1,
                ),
            ),
        )
