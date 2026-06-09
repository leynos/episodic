"""Binding query operations for reference-document services.

Provides ``get_reference_binding`` (fetch by UUID, raises
``ReferenceEntityNotFoundError`` when absent), ``list_reference_bindings``
(paginated listing for a given target kind and target UUID), and
``list_reference_bindings_paged`` (same page plus unpaginated total). Does not
perform writes or validation beyond parsing. All functions are re-exported
through the ``bindings`` façade.
"""

import typing as typ

from .helpers import (
    _parse_target_kind,
    _parse_uuid,
    _validate_pagination,
)
from .types import (
    ReferenceBindingListRequest,
    ReferenceEntityNotFoundError,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import ReferenceBinding
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


async def get_reference_binding(
    uow: CanonicalUnitOfWork,
    *,
    binding_id: str,
) -> ReferenceBinding:
    """Fetch one reusable reference binding by identifier.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit of work providing repository access.
    binding_id : str
        String form of the reference binding UUID.

    Returns
    -------
    ReferenceBinding
        The persisted reusable reference binding matching ``binding_id``.

    Raises
    ------
    ReferenceValidationError
        If ``binding_id`` is not a valid UUID string.
    ReferenceEntityNotFoundError
        If no binding exists for the parsed identifier.
    """
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
    """List reusable reference bindings for one target context.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit of work providing repository access.
    request : ReferenceBindingListRequest
        Typed list request containing target identifiers and pagination values.

    Returns
    -------
    list[ReferenceBinding]
        Bindings matching the requested target context and pagination window.

    Raises
    ------
    ReferenceValidationError
        If pagination values, target kind, or target identifier are invalid.
    """
    _validate_pagination(request.limit, request.offset)
    parsed_target_kind = _parse_target_kind(request.target_kind)
    parsed_target_id = _parse_uuid(request.target_id, "target_id")
    return await uow.reference_bindings.list_for_target(
        target_kind=parsed_target_kind,
        target_id=parsed_target_id,
        limit=request.limit,
        offset=request.offset,
    )


async def list_reference_bindings_paged(
    uow: CanonicalUnitOfWork,
    *,
    request: ReferenceBindingListRequest,
) -> tuple[list[ReferenceBinding], int]:
    """List reusable reference bindings and their unpaginated total."""
    _validate_pagination(request.limit, request.offset)
    parsed_target_kind = _parse_target_kind(request.target_kind)
    parsed_target_id = _parse_uuid(request.target_id, "target_id")
    bindings = await uow.reference_bindings.list_for_target(
        target_kind=parsed_target_kind,
        target_id=parsed_target_id,
        limit=request.limit,
        offset=request.offset,
    )
    total = await uow.reference_bindings.count_for_target(
        target_kind=parsed_target_kind,
        target_id=parsed_target_id,
    )
    return bindings, total
