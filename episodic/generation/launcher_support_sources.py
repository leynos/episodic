"""Load and bound canonical source text for draft-script generation input.

``GenerationSourceLimits`` and ``GenerationSourceLimitError`` define and
enforce the byte and count bounds applied while building one draft's source
input. ``source_from_document`` reads source text from canonical
:class:`~episodic.canonical.domain.SourceDocument` records or the
object-store port, normalizes uploaded content, and returns the
``DraftScriptSource`` consumed by ``DraftScriptGenerator``. These helpers do
not open, commit, or dispose persistence sessions themselves.
"""

import dataclasses as dc
import typing as typ

from episodic.generation.draft_script import (
    DraftScriptGenerationError,
    DraftScriptSource,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import SourceDocument
    from episodic.canonical.object_store import ObjectStorePort

_DEFAULT_MAX_SOURCE_COUNT = 32
_DEFAULT_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_DEFAULT_MAX_AGGREGATE_SOURCE_BYTES = 8 * 1024 * 1024
_DEFAULT_MAX_NORMALIZED_SOURCE_BYTES = 2 * 1024 * 1024


@dc.dataclass(frozen=True, slots=True)
class GenerationSourceLimits:
    """Validated bounds applied while building one draft's source input.

    Attributes
    ----------
    max_source_count : int
        Maximum number of source documents accepted for one draft.
    max_source_bytes : int
        Maximum bytes retained from one source document.
    max_aggregate_source_bytes : int
        Maximum bytes retained across all source documents.
    max_normalized_source_bytes : int
        Maximum UTF-8 bytes after source-text normalisation.

    Raises
    ------
    ValueError
        If any configured bound is less than one.
    """

    max_source_count: int = _DEFAULT_MAX_SOURCE_COUNT
    max_source_bytes: int = _DEFAULT_MAX_SOURCE_BYTES
    max_aggregate_source_bytes: int = _DEFAULT_MAX_AGGREGATE_SOURCE_BYTES
    max_normalized_source_bytes: int = _DEFAULT_MAX_NORMALIZED_SOURCE_BYTES

    def __post_init__(self) -> None:
        """Reject non-positive limits before a launcher begins work."""
        for name, value in dc.asdict(self).items():
            if value < 1:
                msg = f"{name} must be at least 1."
                raise ValueError(msg)


class GenerationSourceLimitError(DraftScriptGenerationError):
    """Raised when bounded generation source input exceeds a configured limit.

    This translated generation error keeps limit rejections stable and free of
    source content, identifiers, and byte counts.
    """

    @classmethod
    def source_count(cls) -> GenerationSourceLimitError:
        """Build the stable source-count rejection."""
        message = "Generation source count exceeds limit."
        return cls(message)

    @classmethod
    def source_bytes(cls) -> GenerationSourceLimitError:
        """Build the stable per-source byte rejection."""
        message = "Generation source exceeds byte limit."
        return cls(message)

    @classmethod
    def aggregate_bytes(cls) -> GenerationSourceLimitError:
        """Build the stable aggregate-byte rejection."""
        message = "Generation source aggregate exceeds byte limit."
        return cls(message)

    @classmethod
    def normalized_bytes(cls) -> GenerationSourceLimitError:
        """Build the stable normalized-text rejection."""
        message = "Generation source exceeds normalized limit."
        return cls(message)


async def source_from_document(
    document: SourceDocument,
    object_store: ObjectStorePort | None,
    limits: GenerationSourceLimits | None = None,
    *,
    remaining_aggregate_bytes: int | None = None,
) -> DraftScriptSource:
    """Build generator source input from canonical source provenance."""
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
    """Read and normalize UTF-8 source text from an upload provenance URI."""
    if object_store is None:
        msg = "An object store is required to load uploaded source content."
        raise DraftScriptGenerationError(msg)
    key = source_uri.removeprefix("upload:")
    payload = await _read_limited_upload_bytes(
        object_store,
        key,
        limits,
        remaining_aggregate_bytes=remaining_aggregate_bytes,
    )
    return _decode_and_normalize_uploaded_source(
        payload,
        key,
        maximum_normalized_bytes=limits.max_normalized_source_bytes,
    )


async def _read_limited_upload_bytes(
    object_store: ObjectStorePort,
    key: str,
    limits: GenerationSourceLimits,
    *,
    remaining_aggregate_bytes: int | None,
) -> bytearray:
    """Read one uploaded object without retaining bytes beyond configured limits."""
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


def _decode_and_normalize_uploaded_source(
    payload: bytearray,
    key: str,
    *,
    maximum_normalized_bytes: int,
) -> str:
    """Convert bounded uploaded bytes to normalized source text."""
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        msg = f"Uploaded source {key!r} is not valid UTF-8 text."
        raise DraftScriptGenerationError(msg) from exc
    normalized = "\n".join(content.splitlines()).strip()
    if not normalized:
        msg = f"Uploaded source {key!r} contains no text."
        raise DraftScriptGenerationError(msg)
    _require_source_size(normalized, maximum_normalized_bytes)
    return normalized


def _require_source_size(content: str, maximum: int) -> None:
    """Reject normalized source text whose UTF-8 representation is too large."""
    if len(content.encode()) > maximum:
        raise GenerationSourceLimitError.normalized_bytes()


def _require_source_byte_limit(content: str, maximum: int) -> None:
    """Reject source content above the configured per-source byte limit."""
    if len(content.encode()) > maximum:
        raise GenerationSourceLimitError.source_bytes()


def _require_aggregate_byte_limit(
    content: str,
    remaining_aggregate_bytes: int | None,
) -> None:
    """Reject source content that exceeds the remaining aggregate budget."""
    if (
        remaining_aggregate_bytes is not None
        and len(content.encode()) > remaining_aggregate_bytes
    ):
        raise GenerationSourceLimitError.aggregate_bytes()
