"""Tests for the episodic public API surface."""

from __future__ import annotations

import episodic


def test_public_api_omits_hello() -> None:
    """Verify the placeholder hello helper is removed from the public API."""
    assert not hasattr(episodic, "hello")
