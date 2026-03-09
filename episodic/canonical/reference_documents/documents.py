"""Document-focused reusable reference-document services."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import ReferenceDocument

from .helpers import (
    _parse_lifecycle_state,
    _parse_reference_kind,
    _parse_uuid,
    _require_reference_document,
    _require_series_exists,
    _validate_pagination,
)
from .types import (
    ReferenceDocumentCreateData,
    ReferenceDocumentListRequest,
    ReferenceDocumentUpdateRequest,
    ReferenceRevisionConflictError,
    ReferenceValidationError,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


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
