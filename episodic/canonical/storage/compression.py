"""Compression helpers for storage-facing text payloads."""

from __future__ import annotations

from compression import zstd

_MINIMUM_COMPRESS_BYTES = 1024


def encode_text_for_storage(
    text: str,
    *,
    minimum_bytes: int = _MINIMUM_COMPRESS_BYTES,
) -> tuple[str, bytes | None]:
    """Return storage values for a text payload.

    Large payloads are compressed and persisted in a binary column, while
    smaller payloads remain in their original text column for readability.
    """
    utf8_bytes = text.encode("utf-8")
    if len(utf8_bytes) < minimum_bytes:
        return text, None

    compressed = zstd.compress(utf8_bytes)
    if len(compressed) >= len(utf8_bytes):
        return text, None
    return "", compressed


def decode_text_from_storage(
    *,
    text_value: str,
    compressed_value: bytes | None,
    field_name: str,
) -> str:
    """Decode a possibly-compressed storage payload into plain UTF-8 text."""
    if compressed_value is None:
        return text_value
    try:
        decompressed = zstd.decompress(compressed_value)
        return decompressed.decode("utf-8")
    except (UnicodeDecodeError, zstd.ZstdError) as exc:
        msg = f"Failed to decompress storage payload for {field_name}."
        raise ValueError(msg) from exc
