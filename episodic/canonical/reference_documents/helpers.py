"""Shared helper utilities for reference-document service operations."""

import dataclasses as dc
import enum
import typing as typ
import uuid

from episodic.canonical.domain import (
    CanonicalEpisode,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)

from .types import (
    ReferenceEntityNotFoundError,
    ReferenceValidationError,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


_MAX_PAGE_LIMIT = 100


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
    if not (1 <= limit <= _MAX_PAGE_LIMIT):
        msg = f"limit must be between 1 and {_MAX_PAGE_LIMIT}."
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


async def _require_episode_exists(
    uow: CanonicalUnitOfWork,
    episode_id: uuid.UUID,
    *,
    field_name: str,
) -> CanonicalEpisode:
    """Raise not-found when an episode does not exist."""
    episode = await uow.episodes.get(episode_id)
    if episode is None:
        msg = f"Episode for {field_name} {episode_id} not found."
        raise ReferenceEntityNotFoundError(msg)
    return episode


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


def _exception_chain(exc: object) -> typ.Iterator[object]:
    """Yield exc and its chained causes/contexts, then `orig`, de-duplicated."""
    seen: set[int] = set()
    roots = (exc, getattr(exc, "orig", exc))
    for root in roots:
        current: object | None = root
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            yield current
            current = getattr(current, "__cause__", None) or getattr(
                current, "__context__", None
            )


def _constraint_name(exc: object) -> str | None:
    """Return the Postgres constraint name when available."""
    for node in _exception_chain(exc):
        direct = getattr(node, "constraint_name", None)
        if direct is not None:
            return typ.cast("str", direct)

    orig_exc = getattr(exc, "orig", exc)
    diag = getattr(orig_exc, "diag", None)
    return typ.cast("str | None", getattr(diag, "constraint_name", None))
