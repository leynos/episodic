"""Compatibility re-exports for reusable reference-document services."""

from .bindings import (
    create_reference_binding,
    get_reference_binding,
    list_reference_bindings,
)
from .documents import (
    create_reference_document,
    get_reference_document,
    list_reference_documents,
    update_reference_document,
)
from .resolution import (
    ResolvedBinding,
    SnapshotContext,
    resolve_bindings,
    snapshot_resolved_bindings,
)
from .revisions import (
    create_reference_document_revision,
    get_reference_document_revision,
    list_reference_document_revisions,
)

__all__: tuple[str, ...] = (
    "ResolvedBinding",
    "SnapshotContext",
    "create_reference_binding",
    "create_reference_document",
    "create_reference_document_revision",
    "get_reference_binding",
    "get_reference_document",
    "get_reference_document_revision",
    "list_reference_bindings",
    "list_reference_document_revisions",
    "list_reference_documents",
    "resolve_bindings",
    "snapshot_resolved_bindings",
    "update_reference_document",
)
