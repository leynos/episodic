"""Tests for source-intake idempotency fingerprint helpers."""

import hashlib

from episodic.canonical.idempotency_service import (
    canonical_json_bytes,
    multipart_request_hash,
)


def test_canonical_json_bytes_are_sorted_and_compact() -> None:
    """Canonical JSON should be stable across input key order."""
    first = canonical_json_bytes({"b": 2, "a": 1})
    second = canonical_json_bytes({"a": 1, "b": 2})

    assert first == b'{"a":1,"b":2}'
    assert first == second


def test_multipart_request_hash_matches_adr_015_worked_vector() -> None:
    """Pin the ADR 015 multipart fingerprint worked example."""
    body_sha256 = hashlib.sha256(b"hello\n").hexdigest()

    result = multipart_request_hash(
        "upload.create",
        body_sha256=body_sha256,
        metadata={
            "content_type": "text/plain",
            "declared_sha256": None,
            "declared_size": 6,
            "ignored": "not part of the operation allowlist",
        },
    )

    assert body_sha256 == (
        "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    )
    assert result == "f03f8d4c738536bcd1c13cc34d6816f8ea0672c3e2d47c2cbbaf5c8ecbda5e2c"
