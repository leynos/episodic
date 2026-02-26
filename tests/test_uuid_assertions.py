"""Shared UUID assertion helpers for test modules."""

from __future__ import annotations

import uuid

UUID7_VERSION = 7


def assert_uuid7(identifier: uuid.UUID, entity_name: str) -> None:
    """Assert a generated identifier uses UUID version 7."""
    assert isinstance(identifier, uuid.UUID), (
        f"Expected {entity_name} ID to be a UUID instance."
    )
    assert identifier.version == UUID7_VERSION, (
        f"Expected {entity_name} ID to use UUIDv7."
    )
