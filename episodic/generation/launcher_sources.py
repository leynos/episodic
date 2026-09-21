"""Bounded source loading for generation launcher input hydration."""

import typing as typ

from episodic.generation.draft_script import (
    DraftScriptGenerationError,
    DraftScriptSource,
)
from episodic.generation.launcher_support import (
    GenerationSourceLimitError,
    GenerationSourceLimits,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import SourceDocument
    from episodic.canonical.object_store import ObjectStorePort


async def source_from_document(
    document: SourceDocument,
    object_store: ObjectStorePort | None,
    limits: GenerationSourceLimits | None = None,
    *,
    remaining_aggregate_bytes: int | None = None,
) -> DraftScriptSource:
    """Build bounded generator source input from canonical provenance."""
    limits = GenerationSourceLimits() if limits is None else limits
    metadata_content = document.metadata.get("content")
    if isinstance(metadata_content, str) and metadata_content.strip():
        content = metadata_content.strip()
    elif document.source_uri.startswith("upload:"):
        content = await _read_uploaded_source(
            document.source_uri,
            object_store,
            limits,
            remaining_aggregate_bytes=remaining_aggregate_bytes,
        )
    else:
        content = document.source_uri
    _require_source_byte_limit(content, limits.max_source_bytes)
    _require_aggregate_byte_limit(content, remaining_aggregate_bytes)
    _require_source_size(content, limits.max_normalized_source_bytes)
    return DraftScriptSource(
        source_id=str(document.id),
        source_type=document.source_type,
        source_uri=document.source_uri,
        content=content,
        weight=document.weight,
    )


async def _read_uploaded_source(
    source_uri: str,
    object_store: ObjectStorePort | None,
    limits: GenerationSourceLimits,
    *,
    remaining_aggregate_bytes: int | None,
) -> str:
    """Read and normalize UTF-8 source text from an upload URI."""
    if object_store is None:
        msg = "An object store is required to load uploaded source content."
        raise DraftScriptGenerationError(msg)
    key = source_uri.removeprefix("upload:")
    payload = await _read_limited_upload_bytes(
        object_store, key, limits, remaining_aggregate_bytes=remaining_aggregate_bytes
    )
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        msg = f"Uploaded source {key!r} is not valid UTF-8 text."
        raise DraftScriptGenerationError(msg) from exc
    normalized = "\n".join(content.splitlines()).strip()
    if not normalized:
        msg = f"Uploaded source {key!r} contains no text."
        raise DraftScriptGenerationError(msg)
    _require_source_size(normalized, limits.max_normalized_source_bytes)
    return normalized


async def _read_limited_upload_bytes(
    object_store: ObjectStorePort,
    key: str,
    limits: GenerationSourceLimits,
    *,
    remaining_aggregate_bytes: int | None,
) -> bytearray:
    """Read an upload while enforcing per-source and aggregate byte limits."""
    payload = bytearray()
    async with object_store.open(key) as chunks:
        async for chunk in chunks:
            size = len(payload) + len(chunk)
            if size > limits.max_source_bytes:
                raise GenerationSourceLimitError.source_bytes()
            if (
                remaining_aggregate_bytes is not None
                and size > remaining_aggregate_bytes
            ):
                raise GenerationSourceLimitError.aggregate_bytes()
            payload.extend(chunk)
    return payload


def _require_source_size(content: str, maximum: int) -> None:
    """Reject normalized source text exceeding its UTF-8 size limit."""
    if len(content.encode()) > maximum:
        raise GenerationSourceLimitError.normalized_bytes()


def _require_source_byte_limit(content: str, maximum: int) -> None:
    """Reject source content above the configured per-source byte limit."""
    if len(content.encode()) > maximum:
        raise GenerationSourceLimitError.source_bytes()


def _require_aggregate_byte_limit(
    content: str, remaining_aggregate_bytes: int | None
) -> None:
    """Reject source content that exceeds the remaining aggregate budget."""
    if (
        remaining_aggregate_bytes is not None
        and len(content.encode()) > remaining_aggregate_bytes
    ):
        raise GenerationSourceLimitError.aggregate_bytes()
