"""Tests for the episodic public API surface.

These tests verify the symbols exposed at the package boundary.

Examples
--------
Import the package to inspect its public surface:

>>> import episodic
"""

from __future__ import annotations

import episodic


def test_public_api_omits_hello() -> None:
    """Verify the placeholder hello helper is removed from the public API."""
    assert not hasattr(episodic, "hello"), (
        "episodic should not expose 'hello' in its public API."
    )
