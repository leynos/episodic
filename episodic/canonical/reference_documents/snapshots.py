"""Snapshot persistence for resolved reference bindings."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import SourceDocument

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork

    from .resolution import ResolvedBinding


def _snapshot_source_uri(resolved_binding: ResolvedBinding) -> str:
    """Build a stable URI for one snapshotted reference revision."""
    return (
        f"ref://{resolved_binding.document.id}/revisions/{resolved_binding.revision.id}"
    )


def _snapshot_metadata(resolved_binding: ResolvedBinding) -> dict[str, object]:
    """Build persisted provenance metadata for one resolved binding snapshot."""
    binding = resolved_binding.binding
    return {
        "binding_id": str(binding.id),
        "target_kind": binding.target_kind.value,
        "document_id": str(resolved_binding.document.id),
        "document_kind": resolved_binding.document.kind.value,
        "owner_series_profile_id": str(
            resolved_binding.document.owner_series_profile_id
        ),
        "effective_from_episode_id": (
            None
            if binding.effective_from_episode_id is None
            else str(binding.effective_from_episode_id)
        ),
    }


def _build_snapshot_source_document(
    *,
    ingestion_job_id: uuid.UUID,
    canonical_episode_id: uuid.UUID | None,
    resolved_binding: ResolvedBinding,
    created_at: dt.datetime,
) -> SourceDocument:
    """Create one provenance source-document entity from a resolved binding."""
    return SourceDocument(
        id=uuid.uuid7(),
        ingestion_job_id=ingestion_job_id,
        canonical_episode_id=canonical_episode_id,
        reference_document_revision_id=resolved_binding.revision.id,
        source_type="reference_document",
        source_uri=_snapshot_source_uri(resolved_binding),
        weight=1.0,
        content_hash=resolved_binding.revision.content_hash,
        metadata=_snapshot_metadata(resolved_binding),
        created_at=created_at,
    )


@dc.dataclass(frozen=True, slots=True)
class SnapshotContext:
    """Job-context parameters for snapshotting resolved bindings as source documents."""

    ingestion_job_id: uuid.UUID
    canonical_episode_id: uuid.UUID | None = None
    created_at: dt.datetime | None = None


async def snapshot_resolved_bindings(
    uow: CanonicalUnitOfWork,
    *,
    resolved: list[ResolvedBinding],
    context: SnapshotContext,
) -> list[SourceDocument]:
    """Persist resolved bindings as provenance source documents.

    This function only snapshots the already-resolved bindings it is given.
    Entity existence and foreign-key integrity are enforced by the repository
    and database layers when the unit of work is flushed or committed.
    """
    if not resolved:
        return []

    effective_created_at = (
        context.created_at
        if context.created_at is not None
        else dt.datetime.now(dt.UTC)
    )
    source_documents = [
        _build_snapshot_source_document(
            ingestion_job_id=context.ingestion_job_id,
            canonical_episode_id=context.canonical_episode_id,
            resolved_binding=resolved_binding,
            created_at=effective_created_at,
        )
        for resolved_binding in resolved
    ]
    for source_document in source_documents:
        await uow.source_documents.add(source_document)
    return source_documents
