"""Binding-target validation helpers for reference-document services.

Validates that binding payloads reference existing, correctly owned domain
entities. Parses raw string fields (UUIDs, target kind) into typed values,
enforces the single-target-identifier invariant, and checks that any
``effective_from_episode_id`` is only present for ``SERIES_PROFILE`` targets.

Does not create or persist any entities. Consumed by ``_binding_creation``
during the ``create_reference_binding`` orchestration flow; the public surface
is exposed through the ``bindings`` façade.
"""

import dataclasses as dc
import typing as typ

from episodic.canonical.domain import ReferenceBindingTargetKind

from .helpers import (
    _BindingTargetAlignment,
    _parse_target_kind,
    _parse_uuid,
    _require_episode_exists,
    _require_series_exists,
)
from .types import (
    ReferenceBindingData,
    ReferenceEntityNotFoundError,
    ReferenceValidationError,
    _ParsedBindingIds,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


class _SeriesOwnedEntity(typ.Protocol):
    series_profile_id: uuid.UUID


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


async def _validate_entity_series_alignment(
    entity_id: uuid.UUID | None,
    fetcher: cabc.Callable[[uuid.UUID], cabc.Awaitable[_SeriesOwnedEntity | None]],
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


def _assert_effective_from_series_profile_only(
    target_kind: ReferenceBindingTargetKind,
    effective_from_episode_id: uuid.UUID | None,
) -> None:
    if (
        effective_from_episode_id is not None
        and target_kind is not ReferenceBindingTargetKind.SERIES_PROFILE
    ):
        msg = (
            "ReferenceBinding effective_from_episode_id is only valid for "
            "series_profile targets."
        )
        raise ReferenceValidationError(msg)


async def _validate_effective_from_episode(
    uow: CanonicalUnitOfWork,
    *,
    effective_from_episode_id: uuid.UUID | None,
    document_owner_series_id: uuid.UUID,
) -> uuid.UUID | None:
    if effective_from_episode_id is None:
        return None
    episode = await _require_episode_exists(
        uow,
        effective_from_episode_id,
        field_name="effective_from_episode_id",
    )
    if episode.series_profile_id != document_owner_series_id:
        msg = (
            "Reference binding effective_from episode does not match "
            "document owner series."
        )
        raise ReferenceValidationError(msg)
    return episode.id


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
