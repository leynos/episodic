"""Binding creation orchestration for reference-document services.

Orchestrates the creation of a ``ReferenceBinding``: parses identifiers via
``_binding_validation``, loads the required revision and document, validates
target ownership and episode constraints, constructs the domain object, and
persists it. Maps SQLAlchemy ``IntegrityError`` violations to typed
``ReferenceConflictError`` exceptions.

Does not implement query operations. The public entry point
``create_reference_binding`` is re-exported through the ``bindings`` façade.
"""

import datetime as dt
import typing as typ
import uuid

from sqlalchemy.exc import IntegrityError

from episodic.canonical.constraints import (
    UQ_REF_DOC_BINDINGS_JOB_REV,
    UQ_REF_DOC_BINDINGS_SERIES_REV_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_SERIES_REV_NO_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_TEMPLATE_REV,
)
from episodic.canonical.domain import ReferenceBinding

from ._binding_validation import (
    _assert_effective_from_series_profile_only,
    _parse_binding_ids,
    _validate_binding_target_alignment,
    _validate_effective_from_episode,
)
from .helpers import (
    _BindingTargetAlignment,
    _constraint_name,
    _require_reference_document,
    _require_reference_revision,
)
from .types import (
    ReferenceBindingData,
    ReferenceConflictError,
    ReferenceValidationError,
    _ParsedBindingIds,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


_BINDING_CONSTRAINT_NAMES = {
    UQ_REF_DOC_BINDINGS_SERIES_REV_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_SERIES_REV_NO_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_TEMPLATE_REV,
    UQ_REF_DOC_BINDINGS_JOB_REV,
}


def _new_binding(
    *,
    ids: _ParsedBindingIds,
    revision_id: uuid.UUID,
    effective_from_episode_id: uuid.UUID | None,
) -> ReferenceBinding:
    try:
        return ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=revision_id,
            target_kind=ids.target_kind,
            series_profile_id=ids.series_profile_id,
            episode_template_id=ids.episode_template_id,
            ingestion_job_id=ids.ingestion_job_id,
            effective_from_episode_id=effective_from_episode_id,
            created_at=dt.datetime.now(dt.UTC),
        )
    except ValueError as exc:
        msg = (
            "Invalid reference binding for "
            f"revision_id={revision_id}, "
            f"series_profile_id={ids.series_profile_id}, "
            f"episode_template_id={ids.episode_template_id}, "
            f"ingestion_job_id={ids.ingestion_job_id}, "
            f"effective_from_episode_id={effective_from_episode_id}: "
            f"{exc}"
        )
        raise ReferenceValidationError(msg) from exc


async def _persist_binding(uow: CanonicalUnitOfWork, binding: ReferenceBinding) -> None:
    try:
        await uow.reference_bindings.add(binding)
        await uow.commit()
    except IntegrityError as exc:
        await uow.rollback()
        if _constraint_name(exc) not in _BINDING_CONSTRAINT_NAMES:
            raise
        msg = "Reference binding conflict: duplicate target/revision binding."
        raise ReferenceConflictError(msg) from exc


async def create_reference_binding(
    uow: CanonicalUnitOfWork,
    *,
    data: ReferenceBindingData,
) -> ReferenceBinding:
    """Create one reusable reference binding.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit of work providing repository access and transaction control.
    data : ReferenceBindingData
        Binding payload containing the revision identifier, target selection,
        and optional effective-from episode identifier.

    Returns
    -------
    ReferenceBinding
        The newly created reusable reference binding.

    Raises
    ------
    ReferenceValidationError
        If any identifier is malformed or the binding payload violates domain
        validation rules.
    ReferenceEntityNotFoundError
        If the referenced revision, document, target entity, or effective-from
        episode does not exist.
    ReferenceConflictError
        If an equivalent revision/target binding already exists.
    """
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
    _assert_effective_from_series_profile_only(
        ids.target_kind,
        ids.effective_from_episode_id,
    )
    effective_from_episode_id = await _validate_effective_from_episode(
        uow,
        effective_from_episode_id=ids.effective_from_episode_id,
        document_owner_series_id=document.owner_series_profile_id,
    )
    binding = _new_binding(
        ids=ids,
        revision_id=revision.id,
        effective_from_episode_id=effective_from_episode_id,
    )
    await _persist_binding(uow, binding)
    return binding
