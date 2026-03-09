"""Shared fixtures and helpers for reference-document service tests."""

import typing as typ

import pytest_asyncio

from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateData,
    SeriesProfileCreateData,
    create_episode_template,
    create_series_profile,
)
from episodic.canonical.reference_documents import (
    ReferenceBindingData,
    ReferenceDocumentCreateData,
    ReferenceDocumentListRequest,
    ReferenceDocumentRevisionData,
    create_reference_binding,
    create_reference_document,
    create_reference_document_revision,
    list_reference_documents,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import (
        ReferenceDocument,
        ReferenceDocumentRevision,
    )


class ServiceFixture(typ.TypedDict):
    """Typed fixture payload for reference-document service tests."""

    primary_profile_id: str
    secondary_profile_id: str
    template_id: str


@pytest_asyncio.fixture
async def service_fixture(
    session_factory: typ.Callable[[], AsyncSession],
) -> ServiceFixture:
    """Create two profiles and one template for service tests."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        primary_profile, _ = await create_series_profile(
            uow,
            data=SeriesProfileCreateData(
                slug="service-reference-primary",
                title="Primary Service Profile",
                description="Primary profile",
                configuration={"tone": "direct"},
            ),
            audit=AuditMetadata(actor="service@example.com", note="Create primary"),
        )
        secondary_profile, _ = await create_series_profile(
            uow,
            data=SeriesProfileCreateData(
                slug="service-reference-secondary",
                title="Secondary Service Profile",
                description="Secondary profile",
                configuration={"tone": "formal"},
            ),
            audit=AuditMetadata(
                actor="service@example.com",
                note="Create secondary",
            ),
        )
        template, _ = await create_episode_template(
            uow,
            series_profile_id=primary_profile.id,
            data=EpisodeTemplateData(
                slug="service-reference-template",
                title="Service Template",
                description="Template for reference docs",
                structure={"segments": ["intro", "analysis", "outro"]},
            ),
            audit=AuditMetadata(
                actor="service@example.com",
                note="Create template",
            ),
        )
    return {
        "primary_profile_id": str(primary_profile.id),
        "secondary_profile_id": str(secondary_profile.id),
        "template_id": str(template.id),
    }


async def _create_binding_test_revision(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
    *,
    content_hash: str,
    metadata_topic: str,
) -> ReferenceDocumentRevision:
    """Create a research-brief document and one revision; return the revision."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        created = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="research_brief",
                lifecycle_state="active",
                metadata={"topic": metadata_topic},
            ),
        )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        return await create_reference_document_revision(
            uow,
            document_id=str(created.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"summary": "binding revision"},
                content_hash=content_hash,
                author="service@example.com",
                change_note="binding revision",
            ),
        )


async def _create_host_and_guest_documents(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> tuple[ReferenceDocument, ReferenceDocument]:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        host_document = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="host_profile",
                lifecycle_state="active",
                metadata={"name": "Host Service Alignment"},
            ),
        )
        guest_document = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="guest_profile",
                lifecycle_state="active",
                metadata={"name": "Guest Service Alignment"},
            ),
        )
    return host_document, guest_document


async def _create_revisions_for_host_and_guest(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
    host_document: ReferenceDocument,
    guest_document: ReferenceDocument,
) -> ReferenceDocumentRevision:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        host_revision = await create_reference_document_revision(
            uow,
            document_id=str(host_document.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"bio": "Host profile"},
                content_hash="service-host-hash-1",
                author="service@example.com",
                change_note="Host revision",
            ),
        )
        _ = await create_reference_document_revision(
            uow,
            document_id=str(guest_document.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"bio": "Guest profile"},
                content_hash="service-guest-hash-1",
                author="service@example.com",
                change_note="Guest revision",
            ),
        )
    return host_revision


async def _list_documents_and_bind(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
    host_revision: ReferenceDocumentRevision,
) -> tuple[list[ReferenceDocument], list[ReferenceDocument]]:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        host_documents = await list_reference_documents(
            uow,
            request=ReferenceDocumentListRequest(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="host_profile",
                limit=10,
                offset=0,
            ),
        )
        guest_documents = await list_reference_documents(
            uow,
            request=ReferenceDocumentListRequest(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="guest_profile",
                limit=10,
                offset=0,
            ),
        )
        await create_reference_binding(
            uow,
            data=ReferenceBindingData(
                reference_document_revision_id=str(host_revision.id),
                target_kind="episode_template",
                series_profile_id=None,
                episode_template_id=service_fixture["template_id"],
                ingestion_job_id=None,
                effective_from_episode_id=None,
            ),
        )
    return host_documents, guest_documents
