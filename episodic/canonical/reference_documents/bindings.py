"""Façade re-exporting binding services from focused sub-modules.

The implementation is split across three private sub-modules:

- ``_binding_validation`` — UUID/enum parsing, target-shape and
  effective-from constraints.
- ``_binding_creation`` — ``create_reference_binding`` orchestrator and
  persistence helpers.
- ``_binding_queries`` — ``get_reference_binding`` and
  ``list_reference_bindings`` and ``list_reference_bindings_paged``.

This façade does not implement validation, persistence, or query logic
itself; it re-exports the focused sub-modules.

All callers should import exclusively from this façade or from
``reference_documents.services`` / ``reference_documents.__init__``.
"""

from ._binding_creation import create_reference_binding
from ._binding_queries import (
    get_reference_binding,
    list_reference_bindings,
    list_reference_bindings_paged,
)

__all__: tuple[str, ...] = (
    "create_reference_binding",
    "get_reference_binding",
    "list_reference_bindings",
    "list_reference_bindings_paged",
)
