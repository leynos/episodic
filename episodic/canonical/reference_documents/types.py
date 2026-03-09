"""Types and errors for reusable reference-document services."""

import dataclasses as dc


@dc.dataclass(frozen=True, slots=True)
class ReferenceDocumentCreateData:
    """Input data for creating a reusable reference document."""

    owner_series_profile_id: str
    kind: str
    lifecycle_state: str
    metadata: dict[str, object]


@dc.dataclass(frozen=True, slots=True)
class ReferenceDocumentUpdateRequest:
    """Input request for optimistic-lock updates to a reference document."""

    document_id: str
    owner_series_profile_id: str
    expected_lock_version: int
    lifecycle_state: str
    metadata: dict[str, object]


@dc.dataclass(frozen=True, slots=True)
class ReferenceDocumentListRequest:
    """Input request for listing reusable reference documents."""

    owner_series_profile_id: str
    kind: str | None
    limit: int
    offset: int


@dc.dataclass(frozen=True, slots=True)
class ReferenceDocumentRevisionData:
    """Input data for creating immutable reference-document revisions."""

    content: dict[str, object]
    content_hash: str
    author: str | None
    change_note: str | None


@dc.dataclass(frozen=True, slots=True)
class ReferenceDocumentRevisionListRequest:
    """Input request for listing immutable reference-document revisions."""

    document_id: str
    owner_series_profile_id: str
    limit: int
    offset: int


@dc.dataclass(frozen=True, slots=True)
class ReferenceBindingData:
    """Input data for binding one revision to a target context."""

    reference_document_revision_id: str
    target_kind: str
    series_profile_id: str | None
    episode_template_id: str | None
    ingestion_job_id: str | None
    effective_from_episode_id: str | None


@dc.dataclass(frozen=True, slots=True)
class ReferenceBindingListRequest:
    """Input request for listing reusable reference bindings."""

    target_kind: str
    target_id: str
    limit: int
    offset: int


class ReferenceDocumentError(Exception):
    """Base error for reusable reference-document services."""


class ReferenceValidationError(ReferenceDocumentError):
    """Raised when reference-document request data is invalid."""


class ReferenceEntityNotFoundError(ReferenceDocumentError):
    """Raised when a referenced entity cannot be found."""


class ReferenceRevisionConflictError(ReferenceDocumentError):
    """Raised when optimistic-lock preconditions fail."""


class ReferenceConflictError(ReferenceDocumentError):
    """Raised when persistence constraints reject a write."""
