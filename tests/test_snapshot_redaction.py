"""Tests for deterministic snapshot UUID redaction."""

import uuid

import pytest

from tests.snapshot_redaction import redact_snapshot_uuids


def test_redact_snapshot_uuids_redacts_dictionary_keys_and_values() -> None:
    """Dictionary UUID keys and values should both be redacted recursively."""
    identifier = uuid.UUID("018fdcf0-0000-7000-8000-000000000001")

    redacted = redact_snapshot_uuids({identifier: {str(identifier): identifier}})

    assert redacted == {"<uuid>": {"<uuid>": "<uuid>"}}, (
        "dictionary UUID keys and values must be redacted recursively"
    )


def test_redact_snapshot_uuids_rejects_colliding_dictionary_keys() -> None:
    """Distinct UUID keys must not be silently overwritten after redaction."""
    first = uuid.UUID("018fdcf0-0000-7000-8000-000000000001")
    second = uuid.UUID("018fdcf0-0000-7000-8000-000000000002")

    with pytest.raises(
        ValueError,
        match="distinct dictionary keys collide after UUID redaction",
    ):
        redact_snapshot_uuids({first: "first", second: "second"})
