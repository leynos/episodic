"""Idempotency helpers for source-intake application services."""

import hashlib
import typing as typ

from episodic.json_canonicalization import canonical_json_bytes

if typ.TYPE_CHECKING:
    from .domain import JsonMapping


MULTIPART_BODY_HASH_METADATA: dict[str, tuple[str, ...]] = {
    "upload.create": ("content_type", "declared_size", "declared_sha256"),
}


def multipart_request_hash(
    operation: str,
    *,
    body_sha256: str,
    metadata: JsonMapping,
) -> str:
    """Return the canonical multipart request fingerprint for an operation."""
    allowlist = MULTIPART_BODY_HASH_METADATA.get(operation, ())
    filtered_metadata = {key: metadata[key] for key in allowlist if key in metadata}
    material = (
        body_sha256.encode("ascii") + b":" + canonical_json_bytes(filtered_metadata)
    )
    return hashlib.sha256(material).hexdigest()
