"""Conflict and binding service tests for reusable reference documents."""

import typing as typ

import pytest
import test_reference_document_service_support as support

from episodic.canonical.reference_documents import (
    ReferenceBindingData,
    ReferenceConflictError,
    ReferenceDocumentCreateData,
    ReferenceDocumentRevisionData,
    ReferenceValidationError,
    create_reference_binding,
    create_reference_document,
    create_reference_document_revision,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


service_fixture = support.service_fixture
ServiceFixture = support.ServiceFixture


@pytest.mark.asyncio
async def test_create_reference_document_revision_duplicate_hash_raises_conflict(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Duplicate revision content hashes should map to reference conflicts."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        created = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="research_brief",
                lifecycle_state="active",
                metadata={"topic": "Duplicate revision"},
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await create_reference_document_revision(
            uow,
            document_id=str(created.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"summary": "first revision"},
                content_hash="duplicate-service-hash",
                author="service@example.com",
                change_note="first",
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ReferenceConflictError):
            await create_reference_document_revision(
                uow,
                document_id=str(created.id),
                owner_series_profile_id=service_fixture["primary_profile_id"],
                data=ReferenceDocumentRevisionData(
                    content={"summary": "second revision"},
                    content_hash="duplicate-service-hash",
                    author="service@example.com",
                    change_note="second",
                ),
            )


@pytest.mark.asyncio
async def test_create_reference_binding_duplicate_target_raises_conflict(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Duplicate revision/target bindings should map to reference conflicts."""
    revision = await support._create_binding_test_revision(
        session_factory,
        service_fixture,
        content_hash="duplicate-binding-hash",
        metadata_topic="Duplicate binding",
    )
    binding_data = ReferenceBindingData(
        reference_document_revision_id=str(revision.id),
        target_kind="episode_template",
        series_profile_id=None,
        episode_template_id=service_fixture["template_id"],
        ingestion_job_id=None,
        effective_from_episode_id=None,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await create_reference_binding(uow, data=binding_data)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ReferenceConflictError):
            await create_reference_binding(uow, data=binding_data)


@pytest.mark.asyncio
async def test_create_reference_binding_rejects_invalid_target_identifier_shapes(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Binding creation should require exactly one target id matching target_kind."""
    revision = await support._create_binding_test_revision(
        session_factory,
        service_fixture,
        content_hash="invalid-binding-shape-hash",
        metadata_topic="Invalid binding shape",
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(
            ReferenceValidationError,
            match="Reference binding must set exactly one target identifier",
        ):
            await create_reference_binding(
                uow,
                data=ReferenceBindingData(
                    reference_document_revision_id=str(revision.id),
                    target_kind="episode_template",
                    series_profile_id=service_fixture["primary_profile_id"],
                    episode_template_id=service_fixture["template_id"],
                    ingestion_job_id=None,
                    effective_from_episode_id=None,
                ),
            )
        with pytest.raises(
            ReferenceValidationError,
            match="Reference binding target_kind does not match populated target",
        ):
            await create_reference_binding(
                uow,
                data=ReferenceBindingData(
                    reference_document_revision_id=str(revision.id),
                    target_kind="episode_template",
                    series_profile_id=service_fixture["primary_profile_id"],
                    episode_template_id=None,
                    ingestion_job_id=None,
                    effective_from_episode_id=None,
                ),
            )


@pytest.mark.asyncio
async def test_create_reference_binding_translates_constructor_validation_errors(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Binding constructor ValueError paths should surface as validation errors."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        created = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="research_brief",
                lifecycle_state="active",
                metadata={"topic": "Binding constructor validation"},
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        revision = await create_reference_document_revision(
            uow,
            document_id=str(created.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"summary": "binding revision"},
                content_hash="binding-constructor-validation-hash",
                author="service@example.com",
                change_note="binding revision",
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(
            ReferenceValidationError,
            match="Invalid reference binding for revision_id=",
        ):
            await create_reference_binding(
                uow,
                data=ReferenceBindingData(
                    reference_document_revision_id=str(revision.id),
                    target_kind="episode_template",
                    series_profile_id=None,
                    episode_template_id=service_fixture["template_id"],
                    ingestion_job_id=None,
                    effective_from_episode_id="00000000-0000-0000-0000-000000000001",
                ),
            )
