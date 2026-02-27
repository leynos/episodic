"""Compression helpers for storage-facing text payloads.

This module centralizes Zstandard encode/decode behavior for large text
payloads persisted in canonical storage tables.

Examples
--------
Compress and decode payloads:

>>> text_value, compressed = encode_text_for_storage("example")
>>> decode_text_from_storage(
...     text_value=text_value,
...     compressed_value=compressed,
...     field_name="example.field",
... )
'example'
"""

from __future__ import annotations

from compression import zstd

_MINIMUM_COMPRESS_BYTES = 1024
_COMPRESSED_TEXT_SENTINEL = "__zstd__"


def encode_text_for_storage(
    text: str,
    *,
    minimum_bytes: int = _MINIMUM_COMPRESS_BYTES,
) -> tuple[str, bytes | None]:
    """Return storage values for a text payload.

    Large payloads are compressed and persisted in a binary column, while
    smaller payloads remain in their original text column for readability.

    Parameters
    ----------
    text : str
        Payload text to encode for storage.
    minimum_bytes : int, default=_MINIMUM_COMPRESS_BYTES
        UTF-8 byte threshold at or above which compression is considered.

    Returns
    -------
    tuple[str, bytes | None]
        Pair of `(text_value, compressed_value)` where `compressed_value` is
        `None` when compression is not used.

    Raises
    ------
    ValueError
        If `minimum_bytes` is negative.
    """
    if minimum_bytes < 0:
        msg = "minimum_bytes must be non-negative."
        raise ValueError(msg)

    utf8_bytes = text.encode("utf-8")
    if len(utf8_bytes) < minimum_bytes:
        return text, None

    compressed = zstd.compress(utf8_bytes)
    if len(compressed) >= len(utf8_bytes):
        return text, None
    return _COMPRESSED_TEXT_SENTINEL, compressed


def decode_text_from_storage(
    *,
    text_value: str,
    compressed_value: bytes | None,
    field_name: str,
) -> str:
    """Decode a possibly-compressed storage payload into plain UTF-8 text.

    Parameters
    ----------
    text_value : str
        Value persisted in the legacy text column.
    compressed_value : bytes | None
        Value persisted in the compressed binary column.
    field_name : str
        Field identifier used in error context.

    Returns
    -------
    str
        Decoded text payload.

    Raises
    ------
    ValueError
        If compressed payload metadata is inconsistent or decompression fails.
    """
    if compressed_value is None:
        if text_value == _COMPRESSED_TEXT_SENTINEL:
            msg = (
                f"Inconsistent compressed payload marker for {field_name}: "
                "sentinel text value present without compressed bytes."
            )
            raise ValueError(msg)
        return text_value
    if text_value != _COMPRESSED_TEXT_SENTINEL:
        msg = (
            f"Inconsistent compressed payload marker for {field_name}: "
            "expected sentinel text value."
        )
        raise ValueError(msg)
    try:
        decompressed = zstd.decompress(compressed_value)
        return decompressed.decode("utf-8")
    except (UnicodeDecodeError, zstd.ZstdError) as exc:
        msg = (
            f"Failed to decompress storage payload for {field_name}: "
            f"{exc.__class__.__name__}: {exc}"
        )
        raise ValueError(msg) from exc
