"""Canonical content-hash helpers."""

import hashlib


def sha256_text(value: str) -> str:
    """Return a prefixed SHA-256 hash for UTF-8 text."""
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
