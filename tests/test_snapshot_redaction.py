"""Tests for deterministic snapshot UUID redaction."""

import uuid

from tests.snapshot_redaction import redact_snapshot_uuids


def test_redact_snapshot_uuids_redacts_dictionary_keys_and_values() -> None:
    """Dictionary UUID keys and values should both be redacted recursively."""
    identifier = uuid.UUID("018fdcf0-0000-7000-8000-000000000001")

    redacted = redact_snapshot_uuids({identifier: {str(identifier): identifier}})

    assert redacted == {"<uuid>": {"<uuid>": "<uuid>"}}, (
        "dictionary UUID keys and values must be redacted recursively"
    )
