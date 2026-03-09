"""Public exports for reusable reference-document services."""

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
from .revisions import (
    create_reference_document_revision,
    get_reference_document_revision,
    list_reference_document_revisions,
)
from .types import (
    ReferenceBindingData,
    ReferenceBindingListRequest,
    ReferenceConflictError,
    ReferenceDocumentCreateData,
    ReferenceDocumentError,
    ReferenceDocumentListRequest,
    ReferenceDocumentRevisionData,
    ReferenceDocumentRevisionListRequest,
    ReferenceDocumentUpdateRequest,
    ReferenceEntityNotFoundError,
    ReferenceRevisionConflictError,
    ReferenceValidationError,
)

__all__: tuple[str, ...] = (
    "ReferenceBindingData",
    "ReferenceBindingListRequest",
    "ReferenceConflictError",
    "ReferenceDocumentCreateData",
    "ReferenceDocumentError",
    "ReferenceDocumentListRequest",
    "ReferenceDocumentRevisionData",
    "ReferenceDocumentRevisionListRequest",
    "ReferenceDocumentUpdateRequest",
    "ReferenceEntityNotFoundError",
    "ReferenceRevisionConflictError",
    "ReferenceValidationError",
    "create_reference_binding",
    "create_reference_document",
    "create_reference_document_revision",
    "get_reference_binding",
    "get_reference_document",
    "get_reference_document_revision",
    "list_reference_bindings",
    "list_reference_document_revisions",
    "list_reference_documents",
    "update_reference_document",
)
