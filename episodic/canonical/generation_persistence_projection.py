"""Private source-document projection helpers for generation persistence."""

import typing as typ

from episodic.canonical.domain import SourceDocument
from episodic.canonical.hashing import sha256_text

if typ.TYPE_CHECKING:
    from episodic.canonical.generation_persistence_types import (
        _SourceDocumentProjection,
    )
    from episodic.canonical.ingestion_sources import IngestionJobSource
    from episodic.canonical.uploads import Upload


def source_document_from_attachment(
    projection: _SourceDocumentProjection,
) -> SourceDocument:
    """Project an intake source attachment into canonical source metadata."""
    return SourceDocument(
        id=projection.document_id,
        ingestion_job_id=projection.source.ingestion_job_id,
        canonical_episode_id=projection.episode_id,
        reference_document_revision_id=None,
        source_type=projection.source.source_type,
        source_uri=source_uri(projection.source, projection.upload),
        weight=projection.source.weight,
        content_hash=source_content_hash(projection.source, projection.upload),
        metadata=projection.source.metadata,
        created_at=projection.now,
    )


def source_uri(source: IngestionJobSource, upload: Upload | None) -> str:
    """Return a stable source URI for canonical provenance."""
    if source.source_uri is not None:
        return source.source_uri
    if upload is not None:
        return f"upload:{upload.storage_key}"
    return f"upload:{source.upload_id}"


def source_content_hash(source: IngestionJobSource, upload: Upload | None) -> str:
    """Return the best available source content hash."""
    match source.metadata.get("content_hash"):
        case str() as metadata_hash if metadata_hash.strip():
            return metadata_hash
    if upload is not None and upload.content_hash:
        return upload.content_hash
    return sha256_text(f"{source.source_type}:{source_uri(source, upload)}")
