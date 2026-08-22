"""Canonical content-hash helpers."""

import hashlib


def sha256_text(value: str) -> str:
    """Return the prefixed SHA-256 digest of UTF-8 encoded text.

    Parameters
    ----------
    value : str
        Text to encode as UTF-8 and hash. The value is accepted as supplied,
        including empty text; it is not stripped or otherwise normalised.

    Returns
    -------
    str
        A string in the exact form ``sha256:<64 lowercase hexadecimal
        characters>``.
    """
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
