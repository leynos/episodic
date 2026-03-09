"""Revision-focused reusable reference-document services."""

import datetime as dt
import typing as typ
import uuid

from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import ReferenceDocumentRevision

from .helpers import (
    _constraint_name,
    _parse_uuid,
    _require_reference_document,
    _require_reference_revision,
    _validate_pagination,
)
from .types import (
    ReferenceConflictError,
    ReferenceDocumentRevisionData,
    ReferenceDocumentRevisionListRequest,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


_REVISION_CONTENT_HASH_CONSTRAINT = "uq_reference_document_revisions_document_hash"


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
        if _constraint_name(exc) != _REVISION_CONTENT_HASH_CONSTRAINT:
            raise
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
