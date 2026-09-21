"""Unit tests for source-intake idempotency response encoding."""

import pytest

from episodic.api.source_idempotency import IdempotentResponse, _encode_outcome


def test_idempotency_outcome_encoding_rejects_large_payloads() -> None:
    """Idempotency replay envelopes are capped at 64 KiB."""
    response = IdempotentResponse(
        "201 Created",
        {"content": "x" * (64 * 1024)},
    )

    with pytest.raises(ValueError, match="64 KiB"):
        _encode_outcome(response)


def test_idempotency_outcome_encoding_accepts_small_payloads() -> None:
    """Replay envelopes below the 64 KiB cap encode to non-empty bytes."""
    response = IdempotentResponse(
        "201 Created",
        {"content": "small payload"},
    )

    payload = _encode_outcome(response)

    assert isinstance(payload, bytes), f"expected bytes, got {type(payload)!r}"
    assert payload, "expected a non-empty serialized replay envelope"
