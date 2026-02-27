"""Unit tests for storage compression helpers."""

from __future__ import annotations

from compression import zstd

import pytest

from episodic.canonical.storage.compression import (
    decode_text_from_storage,
    encode_text_for_storage,
)


def test_encode_text_for_storage_rejects_negative_minimum_bytes() -> None:
    """Encoding rejects negative compression thresholds."""
    with pytest.raises(ValueError, match="minimum_bytes"):
        encode_text_for_storage("hello", minimum_bytes=-1)


def test_decode_text_from_storage_rejects_non_sentinel_marker() -> None:
    """Decoding fails when compressed bytes are paired with non-sentinel text."""
    compressed = zstd.compress(b"hello")
    with pytest.raises(ValueError, match="sentinel"):
        decode_text_from_storage(
            text_value="hello",
            compressed_value=compressed,
            field_name="test.field",
        )


def test_decode_text_from_storage_rejects_sentinel_without_compressed_bytes() -> None:
    """Decoding fails when sentinel text is present without compressed bytes."""
    with pytest.raises(ValueError, match=r"test\.field.*sentinel"):
        decode_text_from_storage(
            text_value="__zstd__",
            compressed_value=None,
            field_name="test.field",
        )


def test_decode_text_from_storage_round_trips_compressed_payload() -> None:
    """Decoding returns original text when sentinel and compressed bytes match."""
    payload = "<TEI>" + ("episode " * 1500) + "</TEI>"
    text_value, compressed_value = encode_text_for_storage(payload, minimum_bytes=0)
    assert compressed_value is not None, "Expected payload to use compressed storage."

    decoded = decode_text_from_storage(
        text_value=text_value,
        compressed_value=compressed_value,
        field_name="test.field",
    )

    assert decoded == payload, "Expected decode helper to return original payload."
