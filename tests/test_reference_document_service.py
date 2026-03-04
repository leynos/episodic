"""Service tests for reusable reference-document workflows."""

import typing as typ

import pytest
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
    ReferenceDocumentRevisionListRequest,
    ReferenceDocumentUpdateRequest,
    ReferenceEntityNotFoundError,
    ReferenceRevisionConflictError,
    create_reference_binding,
    create_reference_document,
    create_reference_document_revision,
    get_reference_document,
    get_reference_document_revision,
    list_reference_document_revisions,
    list_reference_documents,
    update_reference_document,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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


@pytest.mark.asyncio
async def test_series_aligned_host_guest_access_and_binding_workflow(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Host/guest docs should be series aligned and bindable to templates."""
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

    assert len(host_documents) == 1, "Expected one host document for the series."
    assert len(guest_documents) == 1, "Expected one guest document for the series."

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ReferenceEntityNotFoundError):
            await get_reference_document(
                uow,
                document_id=str(host_document.id),
                owner_series_profile_id=service_fixture["secondary_profile_id"],
            )
