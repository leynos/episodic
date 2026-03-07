"""Binding-focused reusable reference-document services."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import ReferenceBinding, ReferenceBindingTargetKind
from episodic.canonical.storage.models import (
    UQ_REF_DOC_BINDINGS_JOB_REV,
    UQ_REF_DOC_BINDINGS_SERIES_REV_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_SERIES_REV_NO_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_TEMPLATE_REV,
)

from .helpers import (
    _BindingTargetAlignment,
    _constraint_name,
    _parse_target_kind,
    _parse_uuid,
    _require_reference_document,
    _require_reference_revision,
    _require_series_exists,
    _validate_pagination,
)
from .types import (
    ReferenceBindingData,
    ReferenceBindingListRequest,
    ReferenceConflictError,
    ReferenceEntityNotFoundError,
    ReferenceValidationError,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


_BINDING_CONSTRAINT_NAMES = {
    UQ_REF_DOC_BINDINGS_SERIES_REV_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_SERIES_REV_NO_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_TEMPLATE_REV,
    UQ_REF_DOC_BINDINGS_JOB_REV,
}


class _SeriesOwnedEntity(typ.Protocol):
    series_profile_id: uuid.UUID


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


@dc.dataclass(frozen=True, slots=True)
class _EntityAlignmentCheck:
    required_msg: str
    not_found_msg: str
    mismatch_msg: str


_EPISODE_TEMPLATE_CHECK = _EntityAlignmentCheck(
    required_msg="episode_template_id is required for episode_template bindings.",
    not_found_msg="Episode template {} not found.",
    mismatch_msg=(
        "Reference binding episode-template target does not match "
        "document owner series."
    ),
)

_INGESTION_JOB_CHECK = _EntityAlignmentCheck(
    required_msg="ingestion_job_id is required for ingestion_job bindings.",
    not_found_msg="Ingestion job {} not found.",
    mismatch_msg=(
        "Reference binding ingestion-job target does not match document owner series."
    ),
)


async def _validate_entity_series_alignment(
    entity_id: uuid.UUID | None,
    fetcher: typ.Callable[[uuid.UUID], typ.Awaitable[_SeriesOwnedEntity | None]],
    check: _EntityAlignmentCheck,
    document_owner_series_id: uuid.UUID,
) -> None:
    """Fetch the target entity, assert it exists, and verify owner-series alignment."""
    if entity_id is None:
        raise ReferenceValidationError(check.required_msg)
    entity = await fetcher(entity_id)
    if entity is None:
        raise ReferenceEntityNotFoundError(check.not_found_msg.format(entity_id))
    if entity.series_profile_id != document_owner_series_id:
        raise ReferenceValidationError(check.mismatch_msg)


def _assert_binding_target_shape(
    target_kind: ReferenceBindingTargetKind,
    target_ids: dict[ReferenceBindingTargetKind, uuid.UUID | None],
) -> None:
    """Assert that exactly one target identifier is populated and matches kind."""
    populated = [kind for kind, value in target_ids.items() if value is not None]
    if len(populated) != 1:
        msg = "Reference binding must set exactly one target identifier."
        raise ReferenceValidationError(msg)
    if populated[0] is not target_kind:
        msg = "Reference binding target_kind does not match populated target."
        raise ReferenceValidationError(msg)


async def _validate_binding_target_alignment(
    uow: CanonicalUnitOfWork,
    *,
    alignment: _BindingTargetAlignment,
) -> None:
    """Validate target context existence and owner-series alignment."""
    _assert_binding_target_shape(
        alignment.target_kind,
        {
            ReferenceBindingTargetKind.SERIES_PROFILE: alignment.series_profile_id,
            ReferenceBindingTargetKind.EPISODE_TEMPLATE: alignment.episode_template_id,
            ReferenceBindingTargetKind.INGESTION_JOB: alignment.ingestion_job_id,
        },
    )
    match alignment.target_kind:
        case ReferenceBindingTargetKind.SERIES_PROFILE:
            await _validate_series_profile_binding_target(
                uow,
                series_profile_id=alignment.series_profile_id,
                document_owner_series_id=alignment.document_owner_series_id,
            )
        case ReferenceBindingTargetKind.EPISODE_TEMPLATE:
            await _validate_entity_series_alignment(
                alignment.episode_template_id,
                uow.episode_templates.get,
                _EPISODE_TEMPLATE_CHECK,
                alignment.document_owner_series_id,
            )
        case ReferenceBindingTargetKind.INGESTION_JOB:
            await _validate_entity_series_alignment(
                alignment.ingestion_job_id,
                uow.ingestion_jobs.get,
                _INGESTION_JOB_CHECK,
                alignment.document_owner_series_id,
            )


@dc.dataclass(frozen=True)
class _ParsedBindingIds:
    revision_id: uuid.UUID
    target_kind: ReferenceBindingTargetKind
    series_profile_id: uuid.UUID | None
    episode_template_id: uuid.UUID | None
    ingestion_job_id: uuid.UUID | None
    effective_from_episode_id: uuid.UUID | None


def _parse_binding_ids(data: ReferenceBindingData) -> _ParsedBindingIds:
    """Parse and validate all UUID/enum fields from a ReferenceBindingData payload."""
    return _ParsedBindingIds(
        revision_id=_parse_uuid(
            data.reference_document_revision_id,
            "reference_document_revision_id",
        ),
        target_kind=_parse_target_kind(data.target_kind),
        series_profile_id=(
            None
            if data.series_profile_id is None
            else _parse_uuid(data.series_profile_id, "series_profile_id")
        ),
        episode_template_id=(
            None
            if data.episode_template_id is None
            else _parse_uuid(data.episode_template_id, "episode_template_id")
        ),
        ingestion_job_id=(
            None
            if data.ingestion_job_id is None
            else _parse_uuid(data.ingestion_job_id, "ingestion_job_id")
        ),
        effective_from_episode_id=(
            None
            if data.effective_from_episode_id is None
            else _parse_uuid(
                data.effective_from_episode_id, "effective_from_episode_id"
            )
        ),
    )


async def create_reference_binding(
    uow: CanonicalUnitOfWork,
    *,
    data: ReferenceBindingData,
) -> ReferenceBinding:
    """Create a target-scoped binding for a pinned revision."""
    ids = _parse_binding_ids(data)

    revision = await _require_reference_revision(uow, ids.revision_id)
    document = await _require_reference_document(
        uow,
        document_id=revision.reference_document_id,
        owner_series_profile_id=None,
    )
    await _validate_binding_target_alignment(
        uow,
        alignment=_BindingTargetAlignment(
            target_kind=ids.target_kind,
            series_profile_id=ids.series_profile_id,
            episode_template_id=ids.episode_template_id,
            ingestion_job_id=ids.ingestion_job_id,
            document_owner_series_id=document.owner_series_profile_id,
        ),
    )

    try:
        binding = ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=revision.id,
            target_kind=ids.target_kind,
            series_profile_id=ids.series_profile_id,
            episode_template_id=ids.episode_template_id,
            ingestion_job_id=ids.ingestion_job_id,
            effective_from_episode_id=ids.effective_from_episode_id,
            created_at=dt.datetime.now(dt.UTC),
        )
    except ValueError as exc:
        msg = (
            "Invalid reference binding for "
            f"revision_id={revision.id}, "
            f"series_profile_id={ids.series_profile_id}, "
            f"episode_template_id={ids.episode_template_id}, "
            f"ingestion_job_id={ids.ingestion_job_id}, "
            f"effective_from_episode_id={ids.effective_from_episode_id}: "
            f"{exc}"
        )
        raise ReferenceValidationError(msg) from exc
    try:
        await uow.reference_bindings.add(binding)
        await uow.commit()
    except IntegrityError as exc:
        await uow.rollback()
        if _constraint_name(exc) not in _BINDING_CONSTRAINT_NAMES:
            raise
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
