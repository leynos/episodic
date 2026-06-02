"""Façade re-exporting binding services from focused sub-modules.

The implementation is split across three private sub-modules:

- ``_binding_validation`` — UUID/enum parsing, target-shape and
  effective-from constraints.
- ``_binding_creation`` — ``create_reference_binding`` orchestrator and
  persistence helpers.
- ``_binding_queries`` — ``get_reference_binding`` and
  ``list_reference_bindings``.

This façade does not implement validation, persistence, or query logic
itself; it re-exports the focused sub-modules.

All callers should import exclusively from this façade or from
``reference_documents.services`` / ``reference_documents.__init__``.
"""

from __future__ import annotations

import typing as typ

from ._binding_creation import create_reference_binding
from ._binding_queries import (
    get_reference_binding,
    list_reference_bindings,
)
from .helpers import (
    _parse_target_kind,
    _parse_uuid,
    _validate_pagination,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import ReferenceBinding
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork

    from .types import ReferenceBindingListRequest


__all__: tuple[str, ...] = (
    "create_reference_binding",
    "get_reference_binding",
    "list_reference_bindings",
    "list_reference_bindings_paged",
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
