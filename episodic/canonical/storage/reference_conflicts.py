"""Conflict translation helpers for reference-document repositories."""

import typing as typ

from episodic.canonical.constraints import (
    UQ_REF_DOC_BINDINGS_JOB_REV,
    UQ_REF_DOC_BINDINGS_SERIES_REV_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_SERIES_REV_NO_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_TEMPLATE_REV,
)
from episodic.canonical.reference_documents.types import ReferenceConflictError

from .integrity_helpers import add_translating_constraint_conflicts

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

REVISION_CONFLICT_CONSTRAINTS = frozenset({
    "uq_reference_document_revisions_document_hash"
})
REVISION_CONFLICT_MESSAGE = (
    "Reference document revision conflict: duplicate content hash."
)
BINDING_CONFLICT_CONSTRAINTS = frozenset({
    UQ_REF_DOC_BINDINGS_SERIES_REV_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_SERIES_REV_NO_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_TEMPLATE_REV,
    UQ_REF_DOC_BINDINGS_JOB_REV,
})
BINDING_CONFLICT_MESSAGE = (
    "Reference binding conflict: duplicate target/revision binding."
)


async def add_with_conflict_translation(
    session: AsyncSession,
    record: object,
    *,
    constraints: frozenset[str],
    conflict_message: str,
) -> None:
    """Add a record while translating the configured constraint conflicts."""
    await add_translating_constraint_conflicts(
        session,
        record,
        constraints=constraints,
        on_conflict=lambda: ReferenceConflictError(conflict_message),
    )
