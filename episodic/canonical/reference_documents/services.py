"""Service functions for reusable reference-document workflows."""

import dataclasses as dc
import datetime as dt
import enum
import typing as typ
import uuid

from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)

from .types import (
    ReferenceBindingData,
    ReferenceBindingListRequest,
    ReferenceConflictError,
    ReferenceDocumentCreateData,
    ReferenceDocumentListRequest,
    ReferenceDocumentRevisionData,
    ReferenceDocumentRevisionListRequest,
    ReferenceDocumentUpdateRequest,
    ReferenceEntityNotFoundError,
    ReferenceRevisionConflictError,
    ReferenceValidationError,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


def _parse_uuid(raw_value: str, field_name: str) -> uuid.UUID:
    """Parse one UUID field from a request payload."""
    try:
        return uuid.UUID(raw_value)
    except (ValueError, TypeError, AttributeError) as exc:
        msg = f"Invalid UUID for {field_name}: {raw_value!r}."
        raise ReferenceValidationError(msg) from exc


def _parse_enum[EnumT: enum.Enum](
    raw_value: str,
    enum_cls: type[EnumT],
    *,
    field_label: str,
) -> EnumT:
    """Parse one enum value and preserve domain-specific error wording."""
    try:
        return enum_cls(raw_value)
    except ValueError as exc:
        msg = f"Unsupported {field_label}: {raw_value!r}."
        raise ReferenceValidationError(msg) from exc


def _parse_reference_kind(raw_value: str) -> ReferenceDocumentKind:
    """Parse a document kind string into the enum value."""
    return _parse_enum(
        raw_value,
        ReferenceDocumentKind,
        field_label="reference document kind",
    )


def _parse_lifecycle_state(raw_value: str) -> ReferenceDocumentLifecycleState:
    """Parse a lifecycle-state string into the enum value."""
    return _parse_enum(
        raw_value,
        ReferenceDocumentLifecycleState,
        field_label="reference document lifecycle_state",
    )


def _parse_target_kind(raw_value: str) -> ReferenceBindingTargetKind:
    """Parse a binding target-kind string into the enum value."""
    return _parse_enum(
        raw_value,
        ReferenceBindingTargetKind,
        field_label="reference binding target_kind",
    )


def _validate_pagination(limit: int, offset: int) -> None:
    """Validate list pagination values."""
    if limit < 1:
        msg = "limit must be a positive integer."
        raise ReferenceValidationError(msg)
    if offset < 0:
        msg = "offset must be a non-negative integer."
        raise ReferenceValidationError(msg)


async def _require_series_exists(
    uow: CanonicalUnitOfWork,
    profile_id: uuid.UUID,
) -> None:
    """Raise not-found when a series profile does not exist."""
    profile = await uow.series_profiles.get(profile_id)
    if profile is None:
        msg = f"Series profile {profile_id} not found."
        raise ReferenceEntityNotFoundError(msg)


async def _require_reference_document(
    uow: CanonicalUnitOfWork,
    *,
    document_id: uuid.UUID,
    owner_series_profile_id: uuid.UUID | None,
) -> ReferenceDocument:
    """Fetch one reference document and enforce optional owner scope."""
    document = await uow.reference_documents.get(document_id)
    if document is None:
        msg = f"Reference document {document_id} not found."
        raise ReferenceEntityNotFoundError(msg)
    if (
        owner_series_profile_id is not None
        and document.owner_series_profile_id != owner_series_profile_id
    ):
        msg = (
            f"Reference document {document_id} is not accessible for "
            f"series profile {owner_series_profile_id}."
        )
        raise ReferenceEntityNotFoundError(msg)
    return document


async def _require_reference_revision(
    uow: CanonicalUnitOfWork,
    revision_id: uuid.UUID,
) -> ReferenceDocumentRevision:
    """Fetch one reference revision by identifier."""
    revision = await uow.reference_document_revisions.get(revision_id)
    if revision is None:
        msg = f"Reference document revision {revision_id} not found."
        raise ReferenceEntityNotFoundError(msg)
    return revision


@dc.dataclass(frozen=True, slots=True)
class _BindingTargetAlignment:
    """Parsed target identifiers for binding-alignment validation."""

    target_kind: ReferenceBindingTargetKind
    series_profile_id: uuid.UUID | None
    episode_template_id: uuid.UUID | None
    ingestion_job_id: uuid.UUID | None
    document_owner_series_id: uuid.UUID


async def create_reference_document(
    uow: CanonicalUnitOfWork,
    *,
    data: ReferenceDocumentCreateData,
) -> ReferenceDocument:
    """Create and persist a reusable reference document."""
    owner_series_profile_id = _parse_uuid(
        data.owner_series_profile_id,
        "owner_series_profile_id",
    )
    await _require_series_exists(uow, owner_series_profile_id)
    now = dt.datetime.now(dt.UTC)
    document = ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=owner_series_profile_id,
        kind=_parse_reference_kind(data.kind),
        lifecycle_state=_parse_lifecycle_state(data.lifecycle_state),
        metadata=data.metadata,
        created_at=now,
        updated_at=now,
        lock_version=1,
    )
    await uow.reference_documents.add(document)
    await uow.commit()
    return document


async def get_reference_document(
    uow: CanonicalUnitOfWork,
    *,
    document_id: str,
    owner_series_profile_id: str | None,
) -> ReferenceDocument:
    """Fetch one reference document with optional owner-scope enforcement."""
    parsed_document_id = _parse_uuid(document_id, "document_id")
    parsed_owner_id = (
        None
        if owner_series_profile_id is None
        else _parse_uuid(owner_series_profile_id, "owner_series_profile_id")
    )
    return await _require_reference_document(
        uow,
        document_id=parsed_document_id,
        owner_series_profile_id=parsed_owner_id,
    )


async def list_reference_documents(
    uow: CanonicalUnitOfWork,
    *,
    request: ReferenceDocumentListRequest,
) -> list[ReferenceDocument]:
    """List reusable reference documents for one owning series profile."""
    _validate_pagination(request.limit, request.offset)
    parsed_owner_id = _parse_uuid(
        request.owner_series_profile_id,
        "owner_series_profile_id",
    )
    await _require_series_exists(uow, parsed_owner_id)
    parsed_kind = None if request.kind is None else _parse_reference_kind(request.kind)
    return await uow.reference_documents.list_for_series(
        parsed_owner_id,
        kind=parsed_kind,
        limit=request.limit,
        offset=request.offset,
    )


async def update_reference_document(
    uow: CanonicalUnitOfWork,
    *,
    request: ReferenceDocumentUpdateRequest,
) -> ReferenceDocument:
    """Update a reference document with optimistic-lock conflict checks."""
    parsed_document_id = _parse_uuid(request.document_id, "document_id")
    parsed_owner_id = _parse_uuid(
        request.owner_series_profile_id,
        "owner_series_profile_id",
    )
    if request.expected_lock_version < 1:
        msg = "expected_lock_version must be a positive integer."
        raise ReferenceValidationError(msg)

    current_document = await _require_reference_document(
        uow,
        document_id=parsed_document_id,
        owner_series_profile_id=parsed_owner_id,
    )

    updated_document = dc.replace(
        current_document,
        lifecycle_state=_parse_lifecycle_state(request.lifecycle_state),
        metadata=request.metadata,
        updated_at=dt.datetime.now(dt.UTC),
        lock_version=request.expected_lock_version + 1,
    )
    updated = await uow.reference_documents.update_with_optimistic_lock(
        updated_document,
        expected_lock_version=request.expected_lock_version,
    )
    if not updated:
        msg = "Reference document revision conflict: concurrent update detected."
        raise ReferenceRevisionConflictError(msg)
    await uow.commit()
    return updated_document


async def create_reference_document_revision(
    uow: CanonicalUnitOfWork,
    *,
    document_id: str,
    owner_series_profile_id: str,
    data: ReferenceDocumentRevisionData,
) -> ReferenceDocumentRevision:
    """Create an immutable revision for one reference document."""
    parsed_document_id = _parse_uuid(document_id, "document_id")
    parsed_owner_id = _parse_uuid(owner_series_profile_id, "owner_series_profile_id")
    document = await _require_reference_document(
        uow,
        document_id=parsed_document_id,
        owner_series_profile_id=parsed_owner_id,
    )

    revision = ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=document.id,
        content=data.content,
        content_hash=data.content_hash,
        author=data.author,
        change_note=data.change_note,
        created_at=dt.datetime.now(dt.UTC),
    )

    try:
        await uow.reference_document_revisions.add(revision)
        await uow.commit()
    except IntegrityError as exc:
        await uow.rollback()
        msg = "Reference document revision conflict: duplicate content hash."
        raise ReferenceConflictError(msg) from exc

    return revision


async def list_reference_document_revisions(
    uow: CanonicalUnitOfWork,
    *,
    request: ReferenceDocumentRevisionListRequest,
) -> list[ReferenceDocumentRevision]:
    """List immutable revisions for one reference document."""
    _validate_pagination(request.limit, request.offset)
    parsed_document_id = _parse_uuid(request.document_id, "document_id")
    parsed_owner_id = _parse_uuid(
        request.owner_series_profile_id,
        "owner_series_profile_id",
    )
    await _require_reference_document(
        uow,
        document_id=parsed_document_id,
        owner_series_profile_id=parsed_owner_id,
    )
    return await uow.reference_document_revisions.list_for_document(
        parsed_document_id,
        limit=request.limit,
        offset=request.offset,
    )


async def get_reference_document_revision(
    uow: CanonicalUnitOfWork,
    *,
    revision_id: str,
    owner_series_profile_id: str | None,
) -> ReferenceDocumentRevision:
    """Fetch one immutable revision and enforce owner-series scope."""
    parsed_revision_id = _parse_uuid(revision_id, "revision_id")
    parsed_owner_id = (
        None
        if owner_series_profile_id is None
        else _parse_uuid(owner_series_profile_id, "owner_series_profile_id")
    )
    revision = await _require_reference_revision(uow, parsed_revision_id)
    await _require_reference_document(
        uow,
        document_id=revision.reference_document_id,
        owner_series_profile_id=parsed_owner_id,
    )
    return revision


async def _validate_series_profile_binding_target(
    uow: CanonicalUnitOfWork,
    *,
    series_profile_id: uuid.UUID | None,
    document_owner_series_id: uuid.UUID,
) -> None:
    """Validate series-profile binding alignment."""
    if series_profile_id is None:
        msg = "series_profile_id is required for series_profile bindings."
        raise ReferenceValidationError(msg)
    await _require_series_exists(uow, series_profile_id)
    if series_profile_id != document_owner_series_id:
        msg = (
            "Reference binding series-profile target does not match "
            "document owner series."
        )
        raise ReferenceValidationError(msg)


async def _validate_episode_template_binding_target(
    uow: CanonicalUnitOfWork,
    *,
    episode_template_id: uuid.UUID | None,
    document_owner_series_id: uuid.UUID,
) -> None:
    """Validate episode-template binding alignment."""
    if episode_template_id is None:
        msg = "episode_template_id is required for episode_template bindings."
        raise ReferenceValidationError(msg)
    template = await uow.episode_templates.get(episode_template_id)
    if template is None:
        msg = f"Episode template {episode_template_id} not found."
        raise ReferenceEntityNotFoundError(msg)
    if template.series_profile_id != document_owner_series_id:
        msg = (
            "Reference binding episode-template target does not match "
            "document owner series."
        )
        raise ReferenceValidationError(msg)


async def _validate_ingestion_job_binding_target(
    uow: CanonicalUnitOfWork,
    *,
    ingestion_job_id: uuid.UUID | None,
    document_owner_series_id: uuid.UUID,
) -> None:
    """Validate ingestion-job binding alignment."""
    if ingestion_job_id is None:
        msg = "ingestion_job_id is required for ingestion_job bindings."
        raise ReferenceValidationError(msg)
    job = await uow.ingestion_jobs.get(ingestion_job_id)
    if job is None:
        msg = f"Ingestion job {ingestion_job_id} not found."
        raise ReferenceEntityNotFoundError(msg)
    if job.series_profile_id != document_owner_series_id:
        msg = (
            "Reference binding ingestion-job target does not match "
            "document owner series."
        )
        raise ReferenceValidationError(msg)


async def _validate_binding_target_alignment(
    uow: CanonicalUnitOfWork,
    *,
    alignment: _BindingTargetAlignment,
) -> None:
    """Validate target context existence and owner-series alignment."""
    match alignment.target_kind:
        case ReferenceBindingTargetKind.SERIES_PROFILE:
            await _validate_series_profile_binding_target(
                uow,
                series_profile_id=alignment.series_profile_id,
                document_owner_series_id=alignment.document_owner_series_id,
            )
        case ReferenceBindingTargetKind.EPISODE_TEMPLATE:
            await _validate_episode_template_binding_target(
                uow,
                episode_template_id=alignment.episode_template_id,
                document_owner_series_id=alignment.document_owner_series_id,
            )
        case ReferenceBindingTargetKind.INGESTION_JOB:
            await _validate_ingestion_job_binding_target(
                uow,
                ingestion_job_id=alignment.ingestion_job_id,
                document_owner_series_id=alignment.document_owner_series_id,
            )


async def create_reference_binding(
    uow: CanonicalUnitOfWork,
    *,
    data: ReferenceBindingData,
) -> ReferenceBinding:
    """Create a target-scoped binding for a pinned revision."""
    revision_id = _parse_uuid(
        data.reference_document_revision_id,
        "reference_document_revision_id",
    )
    target_kind = _parse_target_kind(data.target_kind)
    parsed_series_profile_id = (
        None
        if data.series_profile_id is None
        else _parse_uuid(data.series_profile_id, "series_profile_id")
    )
    parsed_episode_template_id = (
        None
        if data.episode_template_id is None
        else _parse_uuid(data.episode_template_id, "episode_template_id")
    )
    parsed_ingestion_job_id = (
        None
        if data.ingestion_job_id is None
        else _parse_uuid(data.ingestion_job_id, "ingestion_job_id")
    )
    parsed_effective_from_episode_id = (
        None
        if data.effective_from_episode_id is None
        else _parse_uuid(data.effective_from_episode_id, "effective_from_episode_id")
    )

    revision = await _require_reference_revision(uow, revision_id)
    document = await _require_reference_document(
        uow,
        document_id=revision.reference_document_id,
        owner_series_profile_id=None,
    )
    await _validate_binding_target_alignment(
        uow,
        alignment=_BindingTargetAlignment(
            target_kind=target_kind,
            series_profile_id=parsed_series_profile_id,
            episode_template_id=parsed_episode_template_id,
            ingestion_job_id=parsed_ingestion_job_id,
            document_owner_series_id=document.owner_series_profile_id,
        ),
    )

    binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision.id,
        target_kind=target_kind,
        series_profile_id=parsed_series_profile_id,
        episode_template_id=parsed_episode_template_id,
        ingestion_job_id=parsed_ingestion_job_id,
        effective_from_episode_id=parsed_effective_from_episode_id,
        created_at=dt.datetime.now(dt.UTC),
    )
    try:
        await uow.reference_bindings.add(binding)
        await uow.commit()
    except IntegrityError as exc:
        await uow.rollback()
        msg = "Reference binding conflict: duplicate target/revision binding."
        raise ReferenceConflictError(msg) from exc

    return binding


async def get_reference_binding(
    uow: CanonicalUnitOfWork,
    *,
    binding_id: str,
) -> ReferenceBinding:
    """Fetch one reusable reference binding by identifier."""
    parsed_binding_id = _parse_uuid(binding_id, "binding_id")
    binding = await uow.reference_bindings.get(parsed_binding_id)
    if binding is None:
        msg = f"Reference binding {parsed_binding_id} not found."
        raise ReferenceEntityNotFoundError(msg)
    return binding


async def list_reference_bindings(
    uow: CanonicalUnitOfWork,
    *,
    request: ReferenceBindingListRequest,
) -> list[ReferenceBinding]:
    """List reusable reference bindings for one target context."""
    _validate_pagination(request.limit, request.offset)
    parsed_target_kind = _parse_target_kind(request.target_kind)
    parsed_target_id = _parse_uuid(request.target_id, "target_id")
    return await uow.reference_bindings.list_for_target(
        target_kind=parsed_target_kind,
        target_id=parsed_target_id,
        limit=request.limit,
        offset=request.offset,
    )
