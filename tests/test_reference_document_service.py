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
    ReferenceBindingListRequest,
    ReferenceConflictError,
    ReferenceDocumentCreateData,
    ReferenceDocumentError,
    ReferenceDocumentListRequest,
    ReferenceDocumentRevisionData,
    ReferenceDocumentRevisionListRequest,
    ReferenceDocumentUpdateRequest,
    ReferenceEntityNotFoundError,
    ReferenceRevisionConflictError,
    ReferenceValidationError,
    create_reference_binding,
    create_reference_document,
    create_reference_document_revision,
    get_reference_document,
    get_reference_document_revision,
    list_reference_bindings,
    list_reference_document_revisions,
    list_reference_documents,
    update_reference_document,
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


class _SupportsId(typ.Protocol):
    """Structural protocol for objects exposing an identifier."""

    id: object


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
async def test_public_services_reject_invalid_uuid_and_enum_values(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Public service functions should reject invalid UUID and enum values."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(
            ReferenceDocumentError,
            match="Invalid UUID for document_id",
        ):
            await get_reference_document(
                uow,
                document_id="not-a-uuid",
                owner_series_profile_id=service_fixture["primary_profile_id"],
            )

        with pytest.raises(
            ReferenceDocumentError,
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
            ReferenceDocumentError,
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
            ReferenceDocumentError,
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
        with pytest.raises(ReferenceDocumentError, match="limit must be"):
            await list_reference_documents(
                uow,
                request=ReferenceDocumentListRequest(
                    owner_series_profile_id=service_fixture["primary_profile_id"],
                    kind=None,
                    limit=0,
                    offset=0,
                ),
            )

        with pytest.raises(ReferenceDocumentError, match="offset must be"):
            await list_reference_documents(
                uow,
                request=ReferenceDocumentListRequest(
                    owner_series_profile_id=service_fixture["primary_profile_id"],
                    kind=None,
                    limit=10,
                    offset=-1,
                ),
            )


@pytest.mark.asyncio
async def test_list_reference_bindings_rejects_invalid_pagination(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Binding listing should reject invalid pagination values."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ReferenceDocumentError, match="limit must be"):
            await list_reference_bindings(
                uow,
                request=ReferenceBindingListRequest(
                    target_kind="series_profile",
                    target_id=service_fixture["primary_profile_id"],
                    limit=0,
                    offset=0,
                ),
            )

        with pytest.raises(ReferenceDocumentError, match="offset must be"):
            await list_reference_bindings(
                uow,
                request=ReferenceBindingListRequest(
                    target_kind="series_profile",
                    target_id=service_fixture["primary_profile_id"],
                    limit=10,
                    offset=-1,
                ),
            )


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
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        created = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="research_brief",
                lifecycle_state="active",
                metadata={"topic": "Duplicate binding"},
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        revision = await create_reference_document_revision(
            uow,
            document_id=str(created.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"summary": "binding revision"},
                content_hash="duplicate-binding-hash",
                author="service@example.com",
                change_note="binding revision",
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await create_reference_binding(
            uow,
            data=ReferenceBindingData(
                reference_document_revision_id=str(revision.id),
                target_kind="episode_template",
                series_profile_id=None,
                episode_template_id=service_fixture["template_id"],
                ingestion_job_id=None,
                effective_from_episode_id=None,
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ReferenceConflictError):
            await create_reference_binding(
                uow,
                data=ReferenceBindingData(
                    reference_document_revision_id=str(revision.id),
                    target_kind="episode_template",
                    series_profile_id=None,
                    episode_template_id=service_fixture["template_id"],
                    ingestion_job_id=None,
                    effective_from_episode_id=None,
                ),
            )


@pytest.mark.asyncio
async def test_create_reference_binding_rejects_invalid_target_identifier_shapes(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Binding creation should require exactly one target id matching target_kind."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        created = await create_reference_document(
            uow,
            data=ReferenceDocumentCreateData(
                owner_series_profile_id=service_fixture["primary_profile_id"],
                kind="research_brief",
                lifecycle_state="active",
                metadata={"topic": "Invalid binding shape"},
            ),
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        revision = await create_reference_document_revision(
            uow,
            document_id=str(created.id),
            owner_series_profile_id=service_fixture["primary_profile_id"],
            data=ReferenceDocumentRevisionData(
                content={"summary": "binding revision"},
                content_hash="invalid-binding-shape-hash",
                author="service@example.com",
                change_note="binding revision",
            ),
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

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
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
    host_document_with_id = typ.cast("_SupportsId", host_document)
    guest_document_with_id = typ.cast("_SupportsId", guest_document)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        host_revision = await create_reference_document_revision(
            uow,
            document_id=str(host_document_with_id.id),
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
            document_id=str(guest_document_with_id.id),
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
    host_revision_with_id = typ.cast("_SupportsId", host_revision)
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
                reference_document_revision_id=str(host_revision_with_id.id),
                target_kind="episode_template",
                series_profile_id=None,
                episode_template_id=service_fixture["template_id"],
                ingestion_job_id=None,
                effective_from_episode_id=None,
            ),
        )
    return host_documents, guest_documents


@pytest.mark.asyncio
async def test_series_aligned_host_guest_access_and_binding_workflow(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Host/guest docs should be series aligned and bindable to templates."""
    host_document, guest_document = await _create_host_and_guest_documents(
        session_factory,
        service_fixture,
    )
    host_revision = await _create_revisions_for_host_and_guest(
        session_factory,
        service_fixture,
        host_document,
        guest_document,
    )
    host_documents, guest_documents = await _list_documents_and_bind(
        session_factory,
        service_fixture,
        host_revision,
    )

    assert len(host_documents) == 1, "Expected one host document for the series."
    assert len(guest_documents) == 1, "Expected one guest document for the series."

    host_document_with_id = typ.cast("_SupportsId", host_document)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ReferenceEntityNotFoundError):
            await get_reference_document(
                uow,
                document_id=str(host_document_with_id.id),
                owner_series_profile_id=service_fixture["secondary_profile_id"],
            )
