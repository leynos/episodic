"""Conflict and binding service tests for reusable reference documents."""

import datetime as dt
import typing as typ
import uuid

import pytest
import test_reference_document_service_support as support

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    TeiHeader,
)
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


async def _create_draft_episode(
    session_factory: typ.Callable[[], AsyncSession],
    *,
    series_profile_id: str,
    title: str,
) -> CanonicalEpisode:
    now = dt.datetime.now(dt.UTC)
    header = TeiHeader(
        id=uuid.uuid4(),
        title=title,
        payload={"file_desc": {"title": title}},
        raw_xml="<TEI/>",
        created_at=now,
        updated_at=now,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.tei_headers.add(header)
        await uow.commit()

    episode = CanonicalEpisode(
        id=uuid.uuid4(),
        series_profile_id=uuid.UUID(series_profile_id),
        tei_header_id=header.id,
        title=title,
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.episodes.add(episode)
        await uow.commit()
    return episode


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
        with pytest.raises(
            ReferenceConflictError,
            match="duplicate content hash",
        ):
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
        with pytest.raises(
            ReferenceConflictError,
            match="duplicate target/revision binding",
        ):
            await create_reference_binding(uow, data=binding_data)


@pytest.mark.parametrize(
    ("payload_kwargs", "expected_match"),
    [
        (
            {
                "target_kind": "episode_template",
                "series_profile_id": "PRIMARY_PROFILE_ID",
                "episode_template_id": "TEMPLATE_ID",
                "ingestion_job_id": None,
                "effective_from_episode_id": None,
            },
            "Reference binding must set exactly one target identifier",
        ),
        (
            {
                "target_kind": "episode_template",
                "series_profile_id": "PRIMARY_PROFILE_ID",
                "episode_template_id": None,
                "ingestion_job_id": None,
                "effective_from_episode_id": None,
            },
            "Reference binding target_kind does not match populated target",
        ),
    ],
)
@pytest.mark.asyncio
async def test_create_reference_binding_rejects_invalid_target_identifier_shapes(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
    payload_kwargs: dict[str, str | None],
    expected_match: str,
) -> None:
    """Binding creation should require exactly one target id matching target_kind."""
    revision = await support._create_binding_test_revision(
        session_factory,
        service_fixture,
        content_hash="invalid-binding-shape-hash",
        metadata_topic="Invalid binding shape",
    )
    resolved_payload_kwargs = {
        key: (
            service_fixture["primary_profile_id"]
            if value == "PRIMARY_PROFILE_ID"
            else service_fixture["template_id"]
            if value == "TEMPLATE_ID"
            else value
        )
        for key, value in payload_kwargs.items()
    }
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(
            ReferenceValidationError,
            match=expected_match,
        ):
            await create_reference_binding(
                uow,
                data=ReferenceBindingData(
                    reference_document_revision_id=str(revision.id),
                    target_kind=typ.cast("str", resolved_payload_kwargs["target_kind"]),
                    series_profile_id=resolved_payload_kwargs["series_profile_id"],
                    episode_template_id=resolved_payload_kwargs["episode_template_id"],
                    ingestion_job_id=resolved_payload_kwargs["ingestion_job_id"],
                    effective_from_episode_id=resolved_payload_kwargs[
                        "effective_from_episode_id"
                    ],
                ),
            )


@pytest.mark.asyncio
async def test_create_reference_binding_rejects_effective_from_for_non_series_target(
    session_factory: typ.Callable[[], AsyncSession],
    service_fixture: ServiceFixture,
) -> None:
    """Binding creation should reject effective_from on non-series targets."""
    revision = await support._create_binding_test_revision(
        session_factory,
        service_fixture,
        content_hash="binding-constructor-validation-hash",
        metadata_topic="Binding constructor validation",
    )
    episode = await _create_draft_episode(
        session_factory,
        series_profile_id=service_fixture["primary_profile_id"],
        title="Binding constructor validation episode",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(
            ReferenceValidationError,
            match=(
                r"ReferenceBinding effective_from_episode_id is only valid for "
                r"series_profile targets\."
            ),
        ):
            await create_reference_binding(
                uow,
                data=ReferenceBindingData(
                    reference_document_revision_id=str(revision.id),
                    target_kind="episode_template",
                    series_profile_id=None,
                    episode_template_id=service_fixture["template_id"],
                    ingestion_job_id=None,
                    effective_from_episode_id=str(episode.id),
                ),
            )
