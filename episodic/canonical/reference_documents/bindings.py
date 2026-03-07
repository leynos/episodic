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
    target_ids = {
        ReferenceBindingTargetKind.SERIES_PROFILE: alignment.series_profile_id,
        ReferenceBindingTargetKind.EPISODE_TEMPLATE: alignment.episode_template_id,
        ReferenceBindingTargetKind.INGESTION_JOB: alignment.ingestion_job_id,
    }
    populated_targets = [
        kind for kind, value in target_ids.items() if value is not None
    ]
    if len(populated_targets) != 1:
        msg = "Reference binding must set exactly one target identifier."
        raise ReferenceValidationError(msg)
    if populated_targets[0] is not alignment.target_kind:
        msg = "Reference binding target_kind does not match populated target."
        raise ReferenceValidationError(msg)

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
        case _:
            msg = f"Unsupported ReferenceBindingTargetKind: {alignment.target_kind!r}."
            raise ReferenceValidationError(msg)


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
